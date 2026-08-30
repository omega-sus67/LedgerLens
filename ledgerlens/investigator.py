"""The investigator lane: the LLM proposes, the deterministic engine disposes.

This is the module `businessintelligence-ai-redesign.md` section 4.9 specifies and
nothing built. Three call sites, all ADDITIVE to the deterministic spine:

  site 2  propose_tests()      -- extra checks, filled from a fixed template
                                  vocabulary, executed by OUR engine, never by the
                                  model, and excluded from the N score
  site 3  unverified_causes()  -- explanations that live outside the connected data,
                                  each with the source that would settle it
  site 4  narrate_prose()      -- persona-voiced headline and summary, guarded so it
                                  cannot introduce a number

Site 1 of the spec (the LLM event normalizer for Slack/tickets) is deliberately not
built -- see docs/ai_decisions.md D2 for why, and `models.ExtractedSignal` for the
schema it would fill.

**The invariant that makes this safe.** Nothing in this module can change a ranking.
Proposed tests come back as real `ControlResult`s with real `query_id`s, but they are
never passed to `controls.score_n`, so N -- and therefore every hypothesis score, the
rejection of the marketing decoy, and every acceptance test -- is byte-identical
whether this lane runs or not. `tests/test_investigator.py` asserts exactly that.

The model's output is treated as an untrusted proposal at every step: a template name
outside the vocabulary is dropped, a dimension value outside `dim_registry` is
dropped, a cohort that selects no rows is dropped, and a number in the narration that
was not in the payload discards the whole narration. Rejections are counted and shown
rather than hidden -- a validator that never reports catching anything is
indistinguishable from one that is not running.
"""

from __future__ import annotations

import re
from datetime import timedelta

import config
from ledgerlens import contracts, llm
from ledgerlens.models import (
    Anomaly,
    Cohort,
    ControlResult,
    ProposedTest,
    UnverifiedHypothesis,
    Window,
    cohort_is_empty,
    cohort_label,
)
from ledgerlens.store import Store

TEMPLATES = (
    "compare_cohort",
    "check_metric_in_cohort",
    "check_symptom_lift",
    "check_temporal_order",
)

# Keys inside `params` that are NOT dimension names. Everything else in the object is
# treated as a dimension and must survive validation against dim_registry.
RESERVED_PARAMS = {"metric", "prediction", "days_before"}

# The ticket table carries region and segment only -- no payment_rail, no product.
# A symptom check against a dimension the table does not have is not a wrong answer,
# it is an unanswerable question, so it is rejected at validation rather than run and
# silently returned as "no tickets".
TICKET_DIMS = ("region", "segment")

SYSTEM = (
    "You are an investigator embedded in a deterministic root-cause analysis engine "
    "for business metrics. You do NOT decide anything. You propose checks that the "
    "engine will execute in SQL, and the engine's results stand regardless of what "
    "you expected. Never invent a number, a dimension value, a metric name or an "
    "event id: use only the ones given to you. Prefer checks that could FALSIFY the "
    "leading hypothesis over checks that would confirm it."
)

# ------------------------------------------------------------------ schemas
# Written by hand in the portable JSON Schema subset -- see llm.Schema. Deriving
# these from the Pydantic models emits $defs/$ref, which Gemini rejects.

PROPOSE_SCHEMA: llm.Schema = {
    "type": "object",
    "properties": {
        "tests": {
            "type": "array",
            "description": f"At most {config.LLM_TEST_BUDGET} proposed checks.",
            "items": {
                "type": "object",
                "properties": {
                    "template": {"type": "string", "enum": list(TEMPLATES)},
                    "rationale": {
                        "type": "string",
                        "description": "One sentence: what this check would settle, and which hypothesis it threatens.",
                    },
                    "metric": {"type": "string", "description": "Metric to measure. Must be one of the metrics listed."},
                    "prediction": {"type": "string", "enum": ["should_be_flat", "should_also_drop"]},
                    "days_before": {
                        "type": "integer",
                        "description": "check_temporal_order only: how many days before onset to look.",
                    },
                    "region": {"type": "array", "items": {"type": "string"}},
                    "segment": {"type": "array", "items": {"type": "string"}},
                    "payment_rail": {"type": "array", "items": {"type": "string"}},
                    "product": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["template", "rationale", "prediction"],
            },
        }
    },
    "required": ["tests"],
}

UNVERIFIED_SCHEMA: llm.Schema = {
    "type": "object",
    "properties": {
        "causes": {
            "type": "array",
            "description": "At most 4 plausible causes that the CONNECTED data cannot test.",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "The candidate explanation, one sentence."},
                    "needed_source": {"type": "string", "description": "The specific feed or system that would be required to test it."},
                    "would_test": {"type": "string", "description": "The concrete check that source would make possible."},
                },
                "required": ["description", "needed_source", "would_test"],
            },
        }
    },
    "required": ["causes"],
}

NARRATE_SCHEMA: llm.Schema = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "One sentence, under 140 characters."},
        "summary": {"type": "string", "description": "Two to four sentences in the reader's voice."},
    },
    "required": ["headline", "summary"],
}


# ------------------------------------------------------------- validation


def _split_params(raw: dict) -> tuple[Cohort, dict]:
    """Separate the flat params object into a cohort and the reserved controls.

    `ProposedTest.params` is typed `dict[str, str | list[str]]`, which is why the wire
    format is flat rather than a nested cohort object: a dimension maps to a list of
    values, a reserved key maps to a string. The shape enforces itself.
    """
    cohort: Cohort = {}
    control: dict = {}
    for key, value in raw.items():
        if key in ("template", "rationale"):
            continue
        if key in RESERVED_PARAMS:
            if value not in (None, "", []):
                control[key] = value
            continue
        if isinstance(value, list) and value:
            cohort[key] = [str(v) for v in value]
    return cohort, control


def validate(raw: dict, registry: dict[str, list[str]], metrics: list[str]) -> tuple[ProposedTest | None, str]:
    """Turn one untrusted proposal into a ProposedTest, or say why it was rejected.

    Every rejection reason here is a specific hallucination this gate catches. They
    are surfaced in the UI: "4 accepted, 2 rejected" is a stronger claim about the
    system than four accepted checks with no denominator.
    """
    template = raw.get("template")
    if template not in TEMPLATES:
        return None, f"unknown template {template!r}"

    cohort, control = _split_params(raw)
    if not cohort:
        return None, "no cohort given"

    unknown_dims = sorted(set(cohort) - set(registry))
    if unknown_dims:
        return None, f"unknown dimension(s) {unknown_dims}"
    for dim, values in cohort.items():
        bad = sorted(set(values) - set(registry[dim]))
        if bad:
            return None, f"value(s) outside the {dim} universe: {bad}"
    if cohort_is_empty(cohort):
        return None, "cohort selects no rows"

    metric = str(control.get("metric", "")) or ""
    if metric and metric not in metrics:
        return None, f"unknown metric {metric!r}"
    if template == "check_metric_in_cohort" and not metric:
        return None, "check_metric_in_cohort requires a metric"
    if template == "check_symptom_lift":
        outside = sorted(set(cohort) - set(TICKET_DIMS))
        if outside:
            return None, f"the ticket feed carries no {outside} dimension"

    prediction = control.get("prediction")
    if prediction not in ("should_be_flat", "should_also_drop"):
        return None, f"unknown prediction {prediction!r}"

    params: dict[str, str | list[str]] = {k: v for k, v in cohort.items()}
    params["prediction"] = str(prediction)
    if metric:
        params["metric"] = metric
    if template == "check_temporal_order":
        try:
            days = int(control.get("days_before", 14))
        except (TypeError, ValueError):
            return None, "days_before is not an integer"
        if not 1 <= days <= config.PRE_WINDOW_DAYS:
            return None, f"days_before must be between 1 and {config.PRE_WINDOW_DAYS}"
        params["days_before"] = str(days)

    rationale = str(raw.get("rationale", "")).strip() or "(no rationale given)"
    return ProposedTest(template=template, params=params, rationale=rationale), ""


# -------------------------------------------------------------- execution


def _cohort_of(test: ProposedTest) -> Cohort:
    return {k: list(v) for k, v in test.params.items() if isinstance(v, list)}


def _ticket_lift(store: Store, cohort: Cohort, window: Window) -> tuple[float, str]:
    """Ticket volume in the window against the preceding baseline, per day.

    Goes through `store.q` like everything else, so the number a reader sees on an
    AI-proposed check is as replayable as one on a rule-based control. That is the
    whole reason this lane is allowed to put figures on the card at all.
    """
    from ledgerlens.models import cohort_predicate

    base_start = window.start - timedelta(days=config.SYMPTOM_BASELINE_DAYS)
    sql = (
        "SELECT "
        "count(*) FILTER (WHERE created_at::date BETWEEN $ws AND $we) AS in_window, "
        "count(*) FILTER (WHERE created_at::date BETWEEN $bs AND $be) AS in_baseline "
        f"FROM ticket WHERE {cohort_predicate(cohort)}"
    )
    frame, query_id = store.q(
        sql,
        {
            "ws": window.start,
            "we": window.end,
            "bs": base_start,
            "be": window.start - timedelta(days=1),
        },
        label=f"ticket volume {cohort_label(cohort)}",
    )
    row = frame.iloc[0]
    per_day_w = float(row["in_window"]) / max(window.days, 1)
    per_day_b = float(row["in_baseline"]) / max(config.SYMPTOM_BASELINE_DAYS, 1)
    if per_day_b <= 0:
        # No baseline to compare against. Any window volume is then unbounded lift,
        # which is not a percentage -- report it as a large finite move rather than
        # inf so the UI, the guard and json serialisation all stay well defined.
        delta = 100.0 if per_day_w > 0 else 0.0
    else:
        delta = (per_day_w / per_day_b - 1.0) * 100.0
    return delta, query_id


def execute(store: Store, test: ProposedTest, focal: Anomaly) -> ProposedTest:
    """Run one validated proposal through the SAME machinery as a rule-based control.

    `anomaly.measure` and `store.q` are what produce every figure here; the model
    contributed the question and nothing else. On any failure the test comes back
    with `result=None` and is rendered as "not answerable", which is a truthful
    outcome rather than a hidden one.
    """
    from ledgerlens import anomaly as anomaly_mod

    cohort = _cohort_of(test)
    prediction = str(test.params.get("prediction", "should_be_flat"))
    metric = str(test.params.get("metric") or focal.metric)
    window = focal.window
    rule = f"AI:{test.template}"

    if test.template == "check_symptom_lift":
        delta, query_id = _ticket_lift(store, cohort, window)
        observed_metric = "support_tickets"
    else:
        if test.template == "check_temporal_order":
            days = int(str(test.params.get("days_before", 14)))
            window = Window(start=focal.onset - timedelta(days=days), end=focal.onset - timedelta(days=1))
        if metric not in contracts.CONTRACTS:
            return test
        ev, query_id = anomaly_mod.measure(store, metric, cohort, window)
        if ev is None:
            return test
        delta = float(ev.delta_pct)
        observed_metric = metric

    passed = (
        abs(delta) < config.CONTROL_PASS_BAND_PCT
        if prediction == "should_be_flat"
        else delta < -config.CONTROL_PASS_BAND_PCT
    )
    label = f"{cohort_label(cohort)} ({observed_metric})"
    if test.template == "check_temporal_order":
        label += f", {window.start}..{window.end}"
    result = ControlResult(
        name=label,
        cohort=cohort,
        metric=observed_metric,
        prediction=prediction,  # type: ignore[arg-type]
        observed_delta_pct=round(delta, 3),
        passed=passed,
        # NEVER decisive. `decisive` is what `controls.score_n` reads to zero out N,
        # and an LLM-proposed check must not be able to reject a hypothesis. This
        # single False is the mechanical form of "the LLM proposes, evidence
        # disposes" -- see docs/ai_decisions.md D4.
        decisive=False,
        query_id=query_id,
        rule=rule,
    )
    return test.model_copy(update={"result": result})


# ------------------------------------------------------------ site 2: tests


def _describe_context(focal: Anomaly, ranked: list, registry: dict[str, list[str]]) -> str:
    lines = [
        f"METRIC: {focal.metric}",
        f"AFFECTED COHORT: {cohort_label(focal.cohort)}  (as dimensions: {focal.cohort})",
        f"WINDOW: {focal.window.start} to {focal.window.end}, onset {focal.onset}",
        f"OBSERVED: {focal.delta_pct:+.1f}% versus expected ({focal.delta_abs:+,.0f} absolute)",
        "",
        "CANDIDATE EXPLANATIONS ALREADY RANKED BY THE DETERMINISTIC ENGINE:",
    ]
    for i, h in enumerate(ranked[:5], 1):
        lines.append(
            f"  #{i} {h.event.event_id} [{h.event.event_type}] score {h.total:.3f}"
            f" | blast radius {h.event.blast_radius} | {h.event.description}"
        )
        for c in h.controls:
            verdict = "passed" if c.passed else "FAILED"
            lines.append(f"        control already run: {c.rule} on {c.name} -> {verdict} at {c.observed_delta_pct:+.1f}%")
    lines += [
        "",
        "DIMENSION UNIVERSE (any value you use MUST come from these lists):",
    ]
    for dim in sorted(registry):
        lines.append(f"  {dim}: {registry[dim]}")
    lines.append(f"\nMETRICS AVAILABLE: {sorted(contracts.CONTRACTS)}")
    lines.append(f"TICKET FEED DIMENSIONS (check_symptom_lift only): {list(TICKET_DIMS)}")
    return "\n".join(lines)


PROPOSE_PROMPT = """{context}

Propose up to {budget} additional checks that would help confirm or falsify the ranked
explanations above. Do not repeat a control that has already been run.

Templates:
  compare_cohort        - measure the same metric in a DIFFERENT cohort over the same
                          window. Use it to test whether the blast radius is right.
  check_metric_in_cohort- measure a DIFFERENT metric in a cohort. Requires `metric`.
                          Use it to test whether a change hit what it should have hit.
  check_symptom_lift    - support-ticket volume in a cohort against its 28-day
                          baseline. Predict should_be_flat if you believe the cohort
                          was unaffected: a ticket spike then FAILS the check and is
                          evidence the cohort WAS affected.
  check_temporal_order  - measure the metric in a cohort in the `days_before` days
                          BEFORE onset. Predict should_be_flat: movement there means
                          the problem predates the change and the change cannot be
                          the cause.

Give the cohort as dimension keys (region, segment, payment_rail, product), each an
array of values drawn from the universe above. Omit a dimension to leave it
unconstrained. State `prediction` as what SHOULD happen if the leading explanation is
correct."""


def propose_tests(
    store: Store,
    focal: Anomaly,
    ranked: list,
    budget: llm.Budget,
    provider: llm.Provider | None = None,
) -> tuple[list[ProposedTest], list[str]]:
    """Site 2. Returns (executed tests, rejection reasons)."""
    provider = provider or llm.resolve()[0]
    if provider is None:
        return [], []
    registry = store.dim_registry()
    prompt = PROPOSE_PROMPT.format(
        context=_describe_context(focal, ranked, registry), budget=config.LLM_TEST_BUDGET
    )
    data, usage, err = provider.structured(SYSTEM, prompt, PROPOSE_SCHEMA, "propose_tests")
    budget.record(usage)
    if err or not isinstance(data, dict):
        budget.fail("proposed checks", err or "empty response")
        return [], []

    accepted: list[ProposedTest] = []
    rejected: list[str] = []
    seen: set[tuple] = set()
    for raw in (data.get("tests") or [])[: config.LLM_TEST_BUDGET]:
        if not isinstance(raw, dict):
            rejected.append("proposal was not an object")
            continue
        test, why = validate(raw, registry, sorted(contracts.CONTRACTS))
        if test is None:
            rejected.append(why)
            continue
        key = (test.template, tuple(sorted((k, tuple(v) if isinstance(v, list) else v) for k, v in test.params.items())))
        if key in seen:
            rejected.append("duplicate of an earlier proposal")
            continue
        seen.add(key)
        accepted.append(execute(store, test, focal))
    return accepted, rejected


# ------------------------------------------------------ site 3: unverified

UNVERIFIED_PROMPT = """{context}

CONNECTED SOURCE SYSTEMS (everything the engine can actually query): {connected}
KNOWN DRIVERS WITH NO CONNECTED FEED: {anticipated}

List up to 4 plausible causes of this movement that the connected data CANNOT test.
Do not restate the ranked candidates above -- those are already testable. For each,
name the specific feed or system that would be needed and the concrete check it would
make possible. These are explicitly labelled as unverified on the card, so an honest
"we would need X" is worth more than a confident guess."""


def unverified_causes(
    store: Store,
    focal: Anomaly,
    ranked: list,
    contract: contracts.KpiContract | None,
    drop_sources: frozenset[str],
    budget: llm.Budget,
    provider: llm.Provider | None = None,
) -> list[UnverifiedHypothesis]:
    """Site 3. Causes that live outside the ledger, each with the source that would
    settle it.

    Connectivity is read off `contract.lineage` and the gap list off
    `contract.anticipated_event_types` -- the same two fields task 7 made
    load-bearing. Retyping either as prose in a prompt would recreate exactly the bug
    that task fixed, where the card contradicted the demo about what was connected.
    """
    provider = provider or llm.resolve()[0]
    if provider is None:
        return []
    connected = sorted({s.source_system for s in contract.lineage} - set(drop_sources)) if contract else []
    anticipated = sorted(contract.anticipated_event_types) if contract else []
    prompt = UNVERIFIED_PROMPT.format(
        context=_describe_context(focal, ranked, store.dim_registry()),
        connected=connected or "(none)",
        anticipated=anticipated or "(none declared)",
    )
    data, usage, err = provider.structured(SYSTEM, prompt, UNVERIFIED_SCHEMA, "unverified_causes")
    budget.record(usage)
    if err or not isinstance(data, dict):
        budget.fail("unverifiable causes", err or "empty response")
        return []
    out: list[UnverifiedHypothesis] = []
    for raw in (data.get("causes") or [])[:4]:
        if not isinstance(raw, dict):
            continue
        description = str(raw.get("description", "")).strip()
        needed = str(raw.get("needed_source", "")).strip()
        test = str(raw.get("would_test", "")).strip()
        if description and needed and test:
            out.append(UnverifiedHypothesis(description=description, needed_source=needed, would_test=test))
    return out


# ------------------------------------------------- site 4: guarded narration

# Any run of digits, with optional thousands separators and decimals. Deliberately
# greedy about what counts as a number: a guard that under-detects is worthless.
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> set[str]:
    """Every numeric token in `text`, normalised for comparison.

    Normalisation strips thousands separators and trailing zeros so that "410,144"
    and "410144.0" are the same number, while "410" and "411" stay different. Sign
    and unit are stripped by the regex never capturing them: "-8.2%" and "8.2" are
    the same token here, because the guard's question is "where did this DIGIT come
    from", not "is the sign right" -- the sign is prose the template already fixed.
    """
    out = set()
    for raw in _NUMBER.findall(text):
        value = raw.replace(",", "")
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        out.add(value or "0")
    return out


def guard(prose: str, corpus: str) -> list[str]:
    """Numbers in `prose` that do not appear in `corpus`. Empty list means clean.

    This is the anti-hallucination mechanism for the one place an LLM writes text a
    reader will believe. It is deliberately strict and deliberately dumb: the
    narrator is given every figure it may use, so a digit it emits that was not in
    front of it is, without exception, invented. A rounded restatement ("about $400k"
    for -$410,144) trips the guard and loses the narration -- that is the correct
    trade, because the alternative is a tolerance window inside which a wrong number
    is permitted.

    Years and other numerals inside dates are in the corpus already, since the corpus
    carries the same dates the prose is describing.
    """
    return sorted(numbers_in(prose) - numbers_in(corpus))


NARRATE_PROMPT = """You are rewriting a finished diagnosis for one specific reader.

READER: {label} ({depth} depth, reads via {channel})
{rights}

THE DIAGNOSIS, ALREADY VERIFIED -- every figure below came from a logged SQL query:

{corpus}

Rewrite the headline and summary for this reader.

HARD CONSTRAINT: you may use ONLY the numbers that appear above, exactly as they
appear. Do not round them, do not restate them in different units, do not compute new
ones, do not add a percentage or a currency figure of your own. A single invented
digit causes this narration to be discarded and the template version shown instead.
Prefer to write without numbers over writing with an approximate one."""


def narrate_prose(
    payload_corpus: str,
    persona,
    budget: llm.Budget,
    provider: llm.Provider | None = None,
) -> tuple[str, str, list[str]]:
    """Site 4. Returns (headline, summary, guard_rejections).

    Empty strings mean "use the template", which is the outcome for no provider, a
    transport failure, an empty field, or a guard rejection. The caller never has to
    ask why -- `budget.failures` and the returned rejection list carry the reason.
    """
    provider = provider or llm.resolve()[0]
    if provider is None:
        return "", "", []
    rights = (
        "This reader holds every lever."
        if "*" in persona.decision_rights
        else f"This reader can only act on: {', '.join(persona.decision_rights) or 'nothing -- they escalate'}."
    )
    prompt = NARRATE_PROMPT.format(
        label=persona.label, depth=persona.depth, channel=persona.channel, rights=rights, corpus=payload_corpus
    )
    data, usage, err = provider.structured(SYSTEM, prompt, NARRATE_SCHEMA, "narrate")
    budget.record(usage)
    if err or not isinstance(data, dict):
        budget.fail("narration", err or "empty response")
        return "", "", []
    headline = str(data.get("headline", "")).strip()
    summary = str(data.get("summary", "")).strip()
    if not headline or not summary:
        budget.fail("narration", "model returned an empty field")
        return "", "", []
    bad = guard(f"{headline} {summary}", payload_corpus)
    if bad:
        budget.fail("narration", f"numbers guard rejected {bad}")
        return "", "", bad
    return headline, summary, []
