"""The provider seam.

These tests exist because "LLM agnostic" is the kind of claim that is true on the day
it is written and quietly false three commits later, when one vendor's concept leaks
into the interface. So the seam itself is asserted: one method, one schema dialect,
one failure contract, and a registry that cannot describe a provider it cannot build.
"""

from __future__ import annotations

import inspect

import pytest

import config
from ledgerlens import investigator, llm


def test_the_provider_interface_is_exactly_one_method():
    """Every capability this system needs from an LLM is 'JSON matching a schema'. A
    second method here would be the first crack -- it would necessarily describe one
    vendor's feature, and then the investigator would start branching on vendor."""
    methods = [
        n for n, _ in inspect.getmembers(llm.Provider, predicate=inspect.isfunction)
        if not n.startswith("_")
    ]
    assert methods == ["structured"]


@pytest.mark.parametrize("name", sorted(config.PROVIDERS))
def test_every_adapter_implements_the_interface_identically(name):
    adapter = llm._ADAPTERS[name]
    sig = inspect.signature(adapter.structured)
    assert list(sig.parameters) == ["self", "system", "prompt", "schema", "name"]


# ------------------------------------------------------------ schema dialect


def test_gemini_schema_uppercases_types_and_drops_unsupported_keys():
    """Gemini's responseSchema is an OpenAPI subset: it names types with the proto
    spelling and 400s on keys outside the subset. Dropping unknown keys is the safe
    direction -- Pydantic re-applies the validation on the way back in."""
    out = llm._to_gemini_schema(
        {
            "type": "object",
            "title": "NotAllowed",
            "additionalProperties": False,
            "properties": {"xs": {"type": "array", "items": {"type": "string"}, "default": []}},
            "required": ["xs"],
        }
    )
    assert out == {
        "type": "OBJECT",
        "properties": {"xs": {"type": "ARRAY", "items": {"type": "STRING"}}},
        "required": ["xs"],
    }


@pytest.mark.parametrize(
    "schema",
    [investigator.PROPOSE_SCHEMA, investigator.UNVERIFIED_SCHEMA, investigator.NARRATE_SCHEMA],
)
def test_shipped_schemas_survive_the_gemini_adapter_intact(schema):
    """A schema that loses a required field in translation silently degrades to a
    looser contract with the vendor, which is the sort of thing that only shows up as
    a bad answer on stage."""
    adapted = llm._to_gemini_schema(schema)
    assert adapted["required"] == schema["required"]
    assert set(adapted["properties"]) == set(schema["properties"])


@pytest.mark.parametrize(
    "schema",
    [investigator.PROPOSE_SCHEMA, investigator.UNVERIFIED_SCHEMA, investigator.NARRATE_SCHEMA],
)
def test_no_shipped_schema_uses_a_ref(schema):
    """This is why the schemas are hand-written rather than derived from Pydantic:
    `model_json_schema()` emits $defs/$ref for nested models and Gemini rejects them.
    A future edit that reaches for the Pydantic shortcut fails here."""
    assert "$ref" not in repr(schema) and "$defs" not in repr(schema)


# ---------------------------------------------------------------- resolution


def test_a_missing_key_names_the_env_var_that_would_fix_it(monkeypatch):
    """'AI off' with no reason is the silent degradation this product argues against."""
    monkeypatch.setenv("LEDGERLENS_LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    provider, why = llm.resolve("gemini")
    assert provider is None
    assert why == "GEMINI_API_KEY is unset"


def test_an_unknown_provider_lists_the_known_ones(monkeypatch):
    provider, why = llm.resolve("gpt-9")
    assert provider is None
    assert "unknown provider" in why and "gemini" in why and "anthropic" in why


def test_switching_provider_needs_no_source_change(monkeypatch):
    """The migration story, asserted: an env var picks the vendor and the model id
    follows from the registry."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    provider, why = llm.resolve("anthropic")
    assert why == ""
    assert provider.spec.model == config.PROVIDERS["anthropic"].model
    assert isinstance(provider, llm.AnthropicProvider)

    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    provider, _ = llm.resolve("gemini")
    assert isinstance(provider, llm.GeminiProvider)


def test_config_is_importable_with_a_nonsense_provider_in_the_environment():
    """A typo in an env var must not stop the DETERMINISTIC pipeline, which does not
    read this setting at all. `provider_spec` returns None; nothing raises."""
    assert config.provider_spec("not-a-vendor") is None


def test_model_override_applies_without_changing_provider(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODEL_OVERRIDE", "gemini-2.5-pro")
    spec = config.provider_spec("gemini")
    assert spec.name == "gemini" and spec.model == "gemini-2.5-pro"


# -------------------------------------------------------------------- budget


def test_budget_sums_across_call_sites():
    """The three sites fire from two modules at two times, which is why the budget is
    a shared mutable object rather than a return value."""
    budget = llm.Budget()
    budget.record(llm.Usage(100, 20, 0.001))
    budget.record(llm.Usage(50, 10, 0.0005))
    assert budget.calls == 2 and budget.total_tokens == 180
    assert budget.cost_usd == pytest.approx(0.0015)


def test_a_failure_is_recorded_without_a_call_being_counted():
    """A vendor outage costs nothing and must not inflate the call count, but it must
    still be visible -- otherwise it is indistinguishable from having nothing to say."""
    budget = llm.Budget()
    budget.fail("narration", "HTTP 429")
    assert budget.calls == 0
    assert budget.failures == ["narration: HTTP 429"]


@pytest.mark.parametrize("name", sorted(config.PROVIDERS))
def test_pricing_is_per_million_tokens_in_the_right_direction(name):
    spec = config.PROVIDERS[name]
    assert spec.price_out_per_mtok > spec.price_in_per_mtok, "output is never cheaper than input"
    assert llm._price(spec, 1_000_000, 0) == pytest.approx(spec.price_in_per_mtok)
