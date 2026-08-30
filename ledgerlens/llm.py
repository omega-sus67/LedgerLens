"""Provider-agnostic LLM transport. The only module that knows a vendor exists.

Three rules hold this file together:

1. **One capability, not a chat API.** Every call site in this system wants the same
   thing: send a system prompt and a user prompt, get back JSON matching a schema.
   So the interface is exactly that -- `Provider.structured()` -- and nothing else.
   No streaming, no multi-turn, no tool loops. A narrower interface is what makes a
   second provider a 40-line class instead of a port.

2. **Schemas are written once, in the JSON Schema subset both vendors accept**, and
   each provider adapts them to its own wire format. Deriving them from Pydantic via
   `model_json_schema()` looks tempting and does not work: Pydantic emits `$defs` and
   `$ref` for nested models, which Gemini's `responseSchema` rejects outright. The
   wire schema and the internal model are genuinely different concerns, so they are
   written separately and the Pydantic model validates what comes back.

3. **This module never raises into the pipeline.** Every failure -- no key, unknown
   provider, timeout, HTTP error, malformed JSON, schema mismatch -- returns None and
   records a reason. The investigator lane is additive; a vendor outage must degrade
   the card to today's behaviour, never break it.

Adding a provider: one `ProviderSpec` row in `config.PROVIDERS`, one class here. That
is the whole contract.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

import config

# JSON Schema, in the subset that is portable across vendors: object/array/string/
# number/integer/boolean, `properties`, `items`, `required`, `enum`, `description`.
# No $ref, no $defs, no additionalProperties, no oneOf -- Gemini rejects them and
# Anthropic does not need them.
Schema = dict[str, Any]


@dataclass(frozen=True)
class Usage:
    """Token counts for one call. `cost_usd` is priced off the provider spec."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class Budget:
    """Accumulator threaded through the investigator lane.

    Mutable on purpose. The three call sites fire from two different modules
    (`pipeline.diagnose` and `narrate.narrate`) at two different times, and the
    telemetry that reports them is assembled after both -- so they need a shared
    object rather than a return value to sum.

    `failures` is not decoration. A lane that silently returns nothing when the
    vendor is down looks identical to a lane that had nothing to say, and the UI
    must be able to tell those apart.
    """

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    failures: list[str] = field(default_factory=list)

    def record(self, usage: Usage) -> None:
        self.calls += 1
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cost_usd += usage.cost_usd

    def fail(self, where: str, why: str) -> None:
        self.failures.append(f"{where}: {why}")

    def plus(self, other: "Budget") -> "Budget":
        """A NEW budget summing both. Never mutates either operand.

        This exists because of a real bug. The pipeline's budget is attached to the
        payload, and `app.load_payload` CACHES the payload -- so a narration call that
        recorded into it would increment the same object on every re-render. Switching
        persona four times would have reported eight LLM calls and quadruple the cost,
        climbing for as long as the reader kept clicking. Narration now uses its own
        budget and the two are summed at the end, which makes narrate() idempotent
        against a cached payload.
        """
        return Budget(
            calls=self.calls + other.calls,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
            failures=[*self.failures, *other.failures],
        )

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _price(spec: config.ProviderSpec, inp: int, out: int) -> float:
    return (inp / 1e6) * spec.price_in_per_mtok + (out / 1e6) * spec.price_out_per_mtok


class Provider(Protocol):
    """What every vendor adapter must offer. Deliberately one method."""

    spec: config.ProviderSpec

    def structured(self, system: str, prompt: str, schema: Schema, name: str) -> tuple[dict | None, Usage, str]:
        """Return (parsed_json, usage, error). Exactly one of parsed/error is set."""
        ...


# ------------------------------------------------------------------- gemini


def _to_gemini_schema(schema: Schema) -> Schema:
    """Adapt portable JSON Schema to Gemini's `responseSchema`.

    Two differences, both mechanical: Gemini names its types with the proto enum
    spelling (OBJECT, not object), and it rejects keys outside its OpenAPI subset.
    Dropping unknown keys rather than passing them through is the safe direction --
    an unrecognised key is a 400 for the whole request, while a dropped one only
    loosens validation that Pydantic re-applies on the way back in.
    """
    allowed = {"type", "properties", "items", "required", "enum", "description"}
    out: Schema = {}
    for key, value in schema.items():
        if key not in allowed:
            continue
        if key == "type":
            out[key] = str(value).upper()
        elif key == "properties":
            out[key] = {k: _to_gemini_schema(v) for k, v in value.items()}
        elif key == "items":
            out[key] = _to_gemini_schema(value)
        else:
            out[key] = value
    return out


class GeminiProvider:
    """Google Gemini over the REST API, via httpx.

    REST rather than `google-genai` on purpose. httpx is already installed, so this
    adds no dependency; and writing the transport by hand keeps the seam in this
    file honest -- an SDK-shaped abstraction tends to leak its vendor's concepts into
    the interface, which is the thing a provider-agnostic design is trying to avoid.
    """

    BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, spec: config.ProviderSpec, api_key: str) -> None:
        self.spec = spec
        self._key = api_key

    def structured(self, system: str, prompt: str, schema: Schema, name: str) -> tuple[dict | None, Usage, str]:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": _to_gemini_schema(schema),
                "temperature": config.LLM_TEMPERATURE,
                "maxOutputTokens": config.LLM_MAX_OUTPUT_TOKENS,
                # Gemini 2.5 models think by default, and thinking tokens are billed
                # against maxOutputTokens. Measured on the proposed-checks prompt:
                # 1,964 thinking tokens of a 2,048 budget, 68 left for the answer,
                # JSON truncated mid-string -> JSONDecodeError -> silent fallback to
                # the template. Every call site here is structured extraction against
                # a fixed schema; there is nothing to reason about, and
                # `temperature = 0` already declares that intent.
                #
                # Flash accepts a zero budget. Pro does NOT -- its minimum is 128 --
                # and `LEDGERLENS_LLM_MODEL=gemini-2.5-pro` is a documented override,
                # so a flat zero would 400 the moment someone used it.
                "thinkingConfig": {"thinkingBudget": 128 if "pro" in self.spec.model else 0},
            },
        }
        url = f"{self.BASE}/{self.spec.model}:generateContent"
        # Retry once, on 5xx only. A 503 ("model overloaded") is transient and common
        # on free tiers; a 4xx is a bad key or a rejected schema and will fail again,
        # so retrying it only doubles the latency before the same message.
        r = None
        for attempt in (1, 2):
            try:
                r = httpx.post(
                    url,
                    json=body,
                    headers={"x-goog-api-key": self._key},
                    timeout=config.LLM_TIMEOUT_S,
                )
            except Exception as exc:  # network, DNS, timeout
                return None, Usage(), f"transport error ({type(exc).__name__})"
            if r.status_code < 500 or attempt == 2:
                break
            time.sleep(config.LLM_RETRY_BACKOFF_S)
        if r.status_code != 200:
            return None, Usage(), f"HTTP {r.status_code}"
        try:
            data = r.json()
            meta = data.get("usageMetadata", {})
            inp = int(meta.get("promptTokenCount", 0))
            out = int(meta.get("candidatesTokenCount", 0))
            usage = Usage(inp, out, _price(self.spec, inp, out))
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text), usage, ""
        except Exception as exc:
            return None, Usage(), f"unparseable response ({type(exc).__name__})"


# ---------------------------------------------------------------- anthropic


class AnthropicProvider:
    """Anthropic via the official SDK, using forced tool-use for structured output.

    Present so that "provider-agnostic" is a demonstrated property rather than a
    claim: this adapter and the Gemini one share no code path and no wire format --
    one is an SDK with a tool-call protocol, the other is hand-rolled REST with a
    response schema -- and the investigator cannot tell them apart.
    """

    def __init__(self, spec: config.ProviderSpec, api_key: str) -> None:
        self.spec = spec
        self._key = api_key

    def structured(self, system: str, prompt: str, schema: Schema, name: str) -> tuple[dict | None, Usage, str]:
        try:
            import anthropic
        except ImportError:
            return None, Usage(), "anthropic sdk not installed"
        try:
            client = anthropic.Anthropic(api_key=self._key, timeout=config.LLM_TIMEOUT_S)
            msg = client.messages.create(
                model=self.spec.model,
                max_tokens=config.LLM_MAX_OUTPUT_TOKENS,
                temperature=config.LLM_TEMPERATURE,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                tools=[{"name": name, "description": f"Return the {name} result.", "input_schema": schema}],
                tool_choice={"type": "tool", "name": name},
            )
        except Exception as exc:
            return None, Usage(), f"transport error ({type(exc).__name__})"
        inp = int(getattr(msg.usage, "input_tokens", 0))
        out = int(getattr(msg.usage, "output_tokens", 0))
        usage = Usage(inp, out, _price(self.spec, inp, out))
        for block in msg.content:
            if getattr(block, "type", "") == "tool_use":
                return dict(block.input), usage, ""
        return None, usage, "no tool_use block in response"


_ADAPTERS = {"gemini": GeminiProvider, "anthropic": AnthropicProvider}


def resolve(provider: str | None = None) -> tuple[Provider | None, str]:
    """Build the configured provider, or explain in one line why there isn't one.

    The reason string is rendered verbatim in the sidebar. "AI investigator off" with
    no explanation is the kind of silent degradation this system exists to argue
    against, so the disabled state always says which env var would enable it.
    """
    spec = config.provider_spec(provider)
    if spec is None:
        known = ", ".join(sorted(config.PROVIDERS))
        return None, f"unknown provider {provider or config.LLM_PROVIDER!r} (known: {known})"
    key = os.environ.get(spec.api_key_env, "")
    if not key:
        return None, f"{spec.api_key_env} is unset"
    adapter = _ADAPTERS.get(spec.name)
    if adapter is None:
        return None, f"no transport implemented for {spec.name!r}"
    return adapter(spec, key), ""


def available() -> bool:
    return resolve()[0] is not None
