"""Narration.

This is the TEMPLATE branch, which is what runs in tests and on stage. It is written
first and treated as the product; an LLM narrator is an upgrade that swaps the prose,
never the numbers.

Nothing in here computes anything. Every figure is copied from an upstream object
that already carries a query_id, which is what makes each claim clickable back to the
SQL that produced it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date

import config
from ledgerlens import personas
from ledgerlens.models import (
    Action,
    Anomaly,
    DiagnosisCard,
    EvidenceStep,
    Hypothesis,
    Redaction,
    SymptomCluster,
    Telemetry,
    cohort_label,
)

OWNER_BY_SOURCE = {
    "github": "the team owning the service",
    "launchdarkly": "the flag owner",
    "calendar": "growth marketing",
    "pricing_db": "revenue operations",
    "slack": "the on-call engineer",
    "zendesk": "support lead",
}

# Human labels for source systems. These are DISPLAY names only -- which sources
# exist, and whether they are connected, is read off the contract's lineage. Keeping
# the two apart is the point: a label that drifts is cosmetic, a connectivity claim
# that drifts is a lie on the one card whose job is honesty.
SOURCE_LABEL = {
    "github": "deploys (github)",
    "launchdarkly": "feature flags (launchdarkly)",
    "calendar": "campaigns (calendar)",
    "pricing_db": "pricing (pricing_db)",
    "zendesk": "support tickets (zendesk)",
    "billing_db": "the billing ledger (billing_db)",
    "psp_webhook": "authorisation events (psp_webhook)",
    "crm": "the CRM (crm)",
}

# What feed WOULD carry an anticipated driver we have no connector for. Keyed off
# contract.anticipated_event_types, so the "known gap" list is declared once in the
# contract rather than retyped as prose here.
FEED_FOR_ANTICIPATED = {
    "vendor_incident": "vendor status feeds",
    "policy_change": "billing policy change logs",
    "external": "market, competitor and macroeconomic data",
}


# A neutral phrase for the driver, so a CFO card can name the cause without naming
# the event id. `show_event_ids` personas append the id themselves.
DRIVER_LABEL_BY_EVENT_TYPE = {
    "deploy": "a code release to the payment path",
    "feature_flag": "a feature flag rollout",
    "campaign": "a marketing budget change",
    "price_change": "a list-price change",
    "policy_change": "a billing policy change",
    "external": "an external market event",
    "vendor_incident": "a payment vendor incident",
}


# Display names for metrics. .title() renders "mrr_renewals" as "Mrr Renewals",
# which reads as a typo on a card a CFO forwards to the board.
METRIC_LABEL = {
    "mrr_renewals": "MRR renewals",
    "new_logo_bookings": "new logo bookings",
    "payment_success_rate": "Payment success rate",
}


def _metric_label(metric: str) -> str:
    return METRIC_LABEL.get(metric, metric.replace("_", " "))


def _driver_label(event_type: str) -> str:
    return DRIVER_LABEL_BY_EVENT_TYPE.get(event_type, "a recorded change")


@dataclass
class NarrationPayload:
    metric: str
    root: Anomaly
    focal: Anomaly
    nodes: list[Anomaly]
    ranked: list[Hypothesis]
    rejected: list[Hypothesis]
    symptoms: list[SymptomCluster]
    seasonal_pct: float
    seasonal_query_id: str
    no_confident_cause: bool = False
    # Defaulted, and therefore must follow the other defaulted fields: dataclass
    # ordering. Carried, never recomputed -- narration states the refusal, it does
    # not decide it.
    redactions: list[Redaction] = field(default_factory=list)
    # What this diagnosis cost. Carried, never recomputed -- narration reports the
    # measurement, it does not take it (except its own stage, which only it can time).
    telemetry: Telemetry | None = None
    # Source systems simulated as not connected. Narration needs them so the card can
    # name what is missing instead of asserting a hardcoded connectivity story that
    # the simulation has just made false.
    drop_sources: frozenset[str] = frozenset()


def _money(x: float) -> str:
    return f"{'-' if x < 0 else ''}${abs(x):,.0f}"


def _is_rate(metric: str) -> bool:
    from ledgerlens import contracts

    contract = contracts.CONTRACTS.get(metric)
    return contract is not None and contract.unit == "rate"


def _is_sparse(metric: str) -> bool:
    from ledgerlens import contracts

    contract = contracts.CONTRACTS.get(metric)
    return contract is not None and contract.status == "sparse_history"


def _format_value(metric: str, x: float) -> str:
    """Render a LEVEL in its KPI's own unit. `_money` is not universal -- a rate
    formatted as dollars reads "-$0.07", which is both wrong and unreadable."""
    return f"{100 * x:.2f}%" if _is_rate(metric) else _money(x)


def _format_points(metric: str, x: float) -> str:
    """Render a DIFFERENCE in the KPI's unit. For a rate that is percentage POINTS,
    which must not be confused with a percentage change: a rate falling from 98.2%
    to 91.3% is -6.9pp and -7.0%, and those are different numbers."""
    return f"{100 * x:+.2f}pp" if _is_rate(metric) else _money(x)


def _format_magnitude(metric: str, x: float) -> str:
    """An UNSIGNED difference, for prose that already carries the direction
    ("$490,754 below plan"). Still points, not percent, for a rate: writing 6.88%
    where 6.88pp is meant is the confusion _format_points exists to prevent."""
    return f"{100 * abs(x):.2f}pp" if _is_rate(metric) else _money(abs(x))


# Public aliases: app.py needs the same unit rules the card uses, and a UI that
# formats a rate as dollars is the exact bug these exist to prevent.
format_value = _format_value
format_points = _format_points


def _history_days(metric: str, as_of: date) -> int:
    """How much history this KPI actually has, for the sparse-history preamble.

    Read from config rather than counted from the data: the card states a fact about
    the KPI's launch, not about whichever window happens to be loaded.
    """
    from ledgerlens import contracts

    contract = contracts.CONTRACTS.get(metric)
    if contract is None or contract.status != "sparse_history":
        return 0
    return (as_of - config.SPARSE_LAUNCH).days + 1


def _sparse_note(payload: "NarrationPayload") -> str:
    """Stated to EVERY persona, in the same words. Declining to detect is a fact
    about the evidence, and abstention never varies by audience."""
    from ledgerlens import contracts

    contract = contracts.CONTRACTS.get(payload.metric)
    if contract is None or contract.status != "sparse_history":
        return ""
    return (
        f"{payload.metric} has insufficient history for automatic detection "
        f"({_history_days(payload.metric, payload.focal.window.end)} days against a "
        f"{contracts.thresholds(payload.metric).warmup_days}-day warmup), so this "
        f"window was selected manually and the uncertainty here is wider than on an "
        f"established KPI. "
    )


def narrate(
    payload: NarrationPayload,
    persona: personas.Persona | None = None,
    no_confident_cause: bool | None = None,
) -> DiagnosisCard:
    who = persona or personas.get(personas.DEFAULT_PERSONA_ID)
    abstain = payload.no_confident_cause if no_confident_cause is None else no_confident_cause

    start = time.perf_counter()
    card = (
        _no_cause_card(payload, who)
        if (abstain or not payload.ranked)
        else _cause_card(payload, who)
    )
    narrate_ms = (time.perf_counter() - start) * 1000

    if payload.telemetry is None:
        return card

    # Both of these need the FINISHED card: queries_on_card counts its ids, and the
    # narration timing is not knowable until narration is done. Set once, here, so
    # both the cause and no-cause branches are covered from one place.
    #
    # This is narration counting its OWN OUTPUT, not narration computing a number
    # about the data -- the rule it must never break is the second one.
    #
    # Imported inside the function on purpose: pipeline imports narrate at module
    # level, so a top-level import here is a cycle. Mirrors _is_rate()'s lazy
    # `from ledgerlens import contracts`.
    from ledgerlens import pipeline as _pipeline

    telemetry = payload.telemetry.model_copy(
        update={
            "queries_on_card": len(_pipeline.card_query_ids(card)),
            "stage_ms": {**payload.telemetry.stage_ms, "narrate": narrate_ms},
            # total_ms was measured inside diagnose(), which had already returned
            # before narration started. Extend it, or the panel lists a stage that
            # its own total excludes and the share column sums past 100%.
            "total_ms": payload.telemetry.total_ms + narrate_ms,
        }
    )
    return card.model_copy(update={"telemetry": telemetry})


def _route(action: Action, who: personas.Persona) -> Action:
    """Decision rights, made mechanical.

    A persona that does not hold the lever is shown an ESCALATION rather than an
    instruction. Priority, owner, evidence and confidence are untouched -- only the
    imperative changes, because who may pull a lever is a fact about the org, not
    about the evidence.
    """
    if personas.holds(who, action.lever):
        return action
    body = action.action[0].lower() + action.action[1:]
    return action.model_copy(update={"action": f"Escalate to {action.owner}: {body}"})


def _for_persona(actions: list[Action], who: personas.Persona) -> list[Action]:
    return [_route(a, who) for a in actions][: who.max_actions]


def _unexplained(payload: NarrationPayload) -> float:
    """Residual after the calendar is accounted for: (1+observed)/(1+seasonal) - 1."""
    observed = payload.root.delta_pct / 100
    seasonal = payload.seasonal_pct / 100
    return 100 * ((1 + observed) / (1 + seasonal) - 1)


def _prose(
    payload: NarrationPayload, who: personas.Persona, unexplained: float, cohort: str
) -> tuple[str, str]:
    """Persona-specific headline and summary.

    NOTHING here computes a number -- every figure is read off the payload, which is
    shared across all personas. That is what keeps card_query_ids() identical.
    """
    top = payload.ranked[0]
    focal, root = payload.focal, payload.root
    n_pass = sum(1 for c in top.controls if c.passed)
    m = payload.metric
    note = _sparse_note(payload)

    if who.persona_id == "cfo":
        headline = (
            f"{_metric_label(m)}: {_format_magnitude(m, root.delta_abs)} below "
            f"plan for {root.window.start} to {root.window.end}"
        )
        summary = (
            note
            + f"{_metric_label(m)} came in {_format_magnitude(m, root.delta_abs)} "
            f"({root.delta_pct:.1f}%) under baseline for {root.window.start} to "
            f"{root.window.end}. About {abs(payload.seasonal_pct):.1f} points of that is "
            f"normal August seasonality. The remaining {abs(unexplained):.1f} points sit "
            f"almost entirely in one customer group -- {cohort} -- which is "
            f"{_format_points(m, focal.delta_abs)} short against its own baseline. "
            f"{_driver_label(top.event.event_type).capitalize()} is the leading "
            f"explanation, and it survived every check run against it. Treat the "
            f"shortfall as at-risk revenue, not lost revenue, until the fix ships. "
            f"This ranks evidence; it does not prove causation."
        )
        return headline, summary

    if who.persona_id == "oncall":
        headline = (
            f"{top.event.event_id} -- {cohort} {payload.metric} down "
            f"{abs(focal.delta_pct):.0f}%"
        )
        summary = (
            note
            + f"{top.event.event_id} ({top.event.description}) went out "
            f"{top.event.ts_start:%Y-%m-%d %H:%M}. Declared blast radius: "
            f"{cohort_label(top.event.blast_radius)}. {payload.metric} in {cohort} is "
            f"{focal.delta_pct:.0f}% below baseline from {focal.window.start}, "
            f"{_format_points(m, focal.delta_abs)} over {focal.window.days} days. "
            f"Score {top.total:.2f}; {n_pass}/{len(top.controls)} negative controls "
            f"pass. Rollback is the P0. "
            f"This ranks evidence; it does not prove causation."
        )
        return headline, summary

    if who.persona_id == "growth":
        headline = (
            f"{cohort} {payload.metric} down {abs(focal.delta_pct):.0f}% -- "
            f"not attributable to campaign spend"
        )
        rejected_line = (
            f"{_driver_label(payload.rejected[0].event.event_type).capitalize()} was "
            f"tested as a cause and rejected outright: "
            f"{payload.rejected[0].rejection_reason}. "
            if payload.rejected
            else ""
        )
        summary = (
            note
            + f"{payload.metric} in {cohort} is {focal.delta_pct:.0f}% below baseline "
            f"({_format_points(m, focal.delta_abs)}). {rejected_line}"
            f"The leading explanation is {_driver_label(top.event.event_type)} affecting "
            f"how that group pays, not demand. The budget change is still doing what it "
            f"was designed to do to acquisition -- see the P2 below. "
            f"This ranks evidence; it does not prove causation."
        )
        return headline, summary

    # analyst -- today's card, unchanged.
    # "Most consistent with", never "caused by". The rubric ranks evidence; it does
    # not establish causation, and the language should not overclaim what it measured.
    headline = (
        f"{payload.metric} in {cohort} down {abs(focal.delta_pct):.0f}% -- most consistent "
        f"with {top.event.event_id}"
    )
    summary = (
        note
        + f"{payload.metric} is {root.delta_pct:.1f}% below baseline for "
        f"{root.window.start} to {root.window.end}. Roughly {payload.seasonal_pct:.1f}% of that "
        f"is August seasonality; the remaining {unexplained:.1f}% concentrates almost entirely "
        f"in {cohort}, which is down {focal.delta_pct:.0f}% and {_format_points(m, focal.delta_abs)} against "
        f"its own baseline. Of {len(payload.ranked) + len(payload.rejected)} recorded changes "
        f"whose blast radius touches that cohort, {top.event.event_id} scores {top.total:.2f} "
        f"and survives all {len(top.controls)} of its negative controls. "
        + (
            f"{payload.rejected[0].event.event_id} is temporally just as plausible but was "
            f"rejected outright: {payload.rejected[0].rejection_reason}."
            if payload.rejected
            else ""
        )
        + " This ranks evidence; it does not prove causation."
    )
    return headline, summary


def _actions(payload: NarrationPayload, who: personas.Persona) -> list[Action]:
    """The recommendation chain. Persona affects only how the change is NAMED --
    every figure, every query_id and every confidence is identical for all readers."""
    top = payload.ranked[0]
    focal = payload.focal
    cohort = cohort_label(focal.cohort)
    owner = OWNER_BY_SOURCE.get(top.event.source, "the change owner")
    # How this change is named to THIS reader. Personas with show_event_ids=False get
    # the driver phrase instead of the sha; the evidence in `basis` is identical
    # either way, which is the whole point.
    m = payload.metric
    ref = top.event.event_id if who.show_event_ids else _driver_label(top.event.event_type)
    driver = (
        f"{_driver_label(top.event.event_type)} ({ref})"
        if who.show_event_ids
        else _driver_label(top.event.event_type)
    )
    lever = personas.lever_for_event(top.event.event_type)
    actions = [
        Action(
            priority="P0",
            driver=driver,
            lever=lever.lever_id,
            action=(
                f"Roll back or hotfix {ref} for {cohort_label(top.event.blast_radius)}, "
                f"then re-run this diagnosis to confirm recovery."
            ),
            expected_impact=(
                f"Recovers up to {_format_magnitude(m, focal.delta_abs)} of the {focal.window.days}-day "
                f"shortfall if the rollback restores the cohort to its own baseline."
            ),
            owner=owner,
            confidence=top.total,
            monitoring=(
                f"Re-run this diagnosis daily. {cohort} back within "
                f"{config.CONTROL_PASS_BAND_PCT:.0f}% of baseline within 3 days, or escalate."
                + (
                    " Re-assess once this KPI clears its detection warmup; the current "
                    "baseline rests on a short history."
                    if _is_sparse(m)
                    else ""
                )
            ),
            basis=f"{_format_points(m, focal.delta_abs)} shortfall over {focal.window.days} days [{focal.query_id}]",
        ),
        Action(
            priority="P1",
            driver=driver,
            lever="hold_forecast",
            action=(
                (
                    f"Flag {cohort_label({k: v for k, v in focal.cohort.items() if k == 'region'})} "
                    f"collections as at-risk until the rail recovers; do not re-forecast on "
                    f"the assumption these authorisations succeeded."
                )
                if _is_rate(m)
                else (
                    f"Hold the {cohort_label({k: v for k, v in focal.cohort.items() if k == 'region'})} "
                    f"renewals forecast until the rail recovers; treat the shortfall as at-risk, "
                    f"not lost."
                )
            ),
            expected_impact=(
                (
                    "Not quantified in revenue terms: this KPI measures authorisation "
                    "success, not collected revenue, and how much converts depends on "
                    "retry recovery we do not model here."
                )
                if _is_rate(m)
                else (
                    f"Reclassifies {_format_magnitude(m, focal.delta_abs)} from lost to at-risk "
                    f"in the current forecast. No revenue effect on its own."
                )
            ),
            owner=personas.OWNER_LABEL["revops"],
            confidence=top.total,
            monitoring=(
                f"Release the hold after the cohort sits within "
                f"{config.CONTROL_PASS_BAND_PCT:.0f}% of baseline for 3 consecutive days."
            ),
            basis=f"focal cohort actual {_format_value(m, focal.actual)} vs expected {_format_value(m, focal.expected)} [{focal.query_id}]",
        ),
    ]
    for rejected in payload.rejected:
        r_ref = (
            rejected.event.event_id
            if who.show_event_ids
            else _driver_label(rejected.event.event_type)
        )
        r_driver = (
            f"{_driver_label(rejected.event.event_type)} ({r_ref})"
            if who.show_event_ids
            else _driver_label(rejected.event.event_type)
        )
        objective = next(
            (c for c in rejected.controls if c.rule == "R4 objective-mismatch" and c.passed), None
        )
        if objective is not None:
            actions.append(
                Action(
                    priority="P2",
                    driver=r_driver,
                    lever=personas.lever_for_event(rejected.event.event_type).lever_id,
                    action=(
                        f"Separately: {r_ref} did not cause this, but it is "
                        f"doing what it was designed to do to {objective.metric}. Confirm that "
                        f"trade-off is intended."
                    ),
                    expected_impact=(
                        f"Restoring the budget would be expected to recover the "
                        f"{abs(objective.observed_delta_pct):.0f}% drop in {objective.metric}; "
                        f"it would not affect this incident."
                    ),
                    owner=OWNER_BY_SOURCE.get(rejected.event.source, "the change owner"),
                    confidence=1.0,  # a measured control delta, not a ranking
                    monitoring=(
                        f"Track {objective.metric} in {cohort_label(objective.cohort)} weekly "
                        f"against its pre-change baseline."
                    ),
                    basis=f"{objective.metric} {objective.observed_delta_pct:+.1f}% in "
                    f"{cohort_label(objective.cohort)} [{objective.query_id}]",
                )
            )

    return actions


def _redaction_sentence(payload: NarrationPayload) -> str:
    """One sentence per policy, built from the AccessRule's own strings.

    Deliberately does NOT count the hidden slices. Producing that count means running
    the unrestricted drill -- i.e. computing the very answer this reader is not
    entitled to, in the process that renders their page. A redaction notice that must
    first compute the secret is not a redaction. The dimension, the policy id and the
    reason are enough to make the refusal attributable, and they are free.
    """
    if not payload.redactions:
        return ""
    by_policy: dict[str, list[str]] = {}
    reasons: dict[str, str] = {}
    for r in payload.redactions:
        by_policy.setdefault(r.policy_id, []).append(r.dim)
        reasons[r.policy_id] = r.reason
    out = []
    for policy_id, dims in by_policy.items():
        cuts = ", ".join(f"`{d}`" for d in sorted(set(dims)))
        out.append(
            f" Deeper cuts by {cuts} are redacted from this view by policy "
            f"`{policy_id}`: {reasons[policy_id].rstrip('.')}. The figures above are "
            f"the most specific slice you are entitled to, not the most specific "
            f"slice that exists."
        )
    return "".join(out)


def _cause_card(payload: NarrationPayload, who: personas.Persona) -> DiagnosisCard:
    top = payload.ranked[0]
    focal, root = payload.focal, payload.root
    cohort = cohort_label(focal.cohort)
    unexplained = _unexplained(payload)

    steps = [
        EvidenceStep(
            claim=(
                f"{payload.metric} fell {root.delta_pct:.1f}% against its deseasonalized "
                f"baseline over {root.window.start} to {root.window.end}."
            ),
            query_id=root.query_id,
            observed=f"actual {_format_value(payload.metric, root.actual)} vs expected {_format_value(payload.metric, root.expected)}",
        ),
        EvidenceStep(
            claim=(
                (
                    f"No seasonal adjustment is applied: {payload.metric} launched "
                    f"{config.SPARSE_LAUNCH} and has no prior August to compare against, "
                    f"so the whole {unexplained:.1f}% is unexplained rather than "
                    f"partly calendar. "
                )
                if _is_sparse(payload.metric)
                else f"About {payload.seasonal_pct:.1f}% of that is ordinary August seasonality, "
                f"measured from the same cohort a year earlier. That leaves "
                f"{unexplained:.1f}% genuinely unexplained."
            ),
            query_id=payload.seasonal_query_id,
            observed=f"seasonal component {payload.seasonal_pct:.1f}%",
        ),
        EvidenceStep(
            claim=(
                f"Attribution narrows the drop to {cohort}, which is {focal.delta_pct:.1f}% "
                f"down on its own and accounts for {100 * focal.contribution:.0f}% of its "
                f"parent's shortfall."
            ),
            query_id=focal.query_id,
            observed=f"shortfall {_format_points(payload.metric, focal.delta_abs)} (z = {focal.residual_z:.1f})",
        ),
        EvidenceStep(
            claim=(
                f"{top.event.description} started {top.event.ts_start:%Y-%m-%d %H:%M}, with a "
                f"declared blast radius of {cohort_label(top.event.blast_radius)} recorded by "
                f"{top.event.source}."
            ),
            query_id=top.query_ids[0],
            observed=(
                f"T={top.scores.T:.2f}, C={top.scores.C:.2f} "
                f"(blast radius overlaps the affected rows)"
            ),
        ),
    ]

    for control in [c for c in top.controls if c.passed][:3]:
        outcome = (
            "should have been unaffected, and it was"
            if control.prediction == "should_be_flat"
            else "should have moved too, and it did"
        )
        steps.append(
            EvidenceStep(
                claim=f"Negative control: {control.name} {outcome}.",
                query_id=control.query_id,
                observed=f"{control.observed_delta_pct:+.1f}%",
            )
        )

    for cluster in top.symptoms[:1]:
        steps.append(
            EvidenceStep(
                claim=(
                    f"Support corroboration: {cluster.volume} tickets keyed {cluster.key} in "
                    f"{cohort_label(cluster.cohort)} from {cluster.first_seen}, against a "
                    f"baseline of {cluster.baseline_volume:.1f} for a window this long."
                ),
                query_id=cluster.query_id,
                observed=f"{cluster.lift:.0f}x lift",
            )
        )

    for rejected in payload.rejected:
        killer = next((c for c in rejected.controls if c.decisive), None)
        if killer is None:
            continue
        steps.append(
            EvidenceStep(
                claim=(
                    f"Rejected: {rejected.event.event_id}. If that were the cause, "
                    f"{killer.name} should have dropped too. It did not."
                ),
                query_id=killer.query_id,
                observed=f"{killer.observed_delta_pct:+.1f}% (expected below "
                f"{-config.CONTROL_PASS_BAND_PCT:.0f}%)",
            )
        )

    headline, summary = _prose(payload, who, unexplained, cohort)
    summary = summary + _redaction_sentence(payload)

    actions = _for_persona(_actions(payload, who), who)

    return DiagnosisCard(
        headline=headline,
        summary=summary,
        causal_chain=steps,
        effect=None,  # no bootstrap in this build; the shortfall is reported as observed
        ranked=payload.ranked,
        rejected=payload.rejected,
        open_question=None,
        actions=actions,
        proposed_tests=[],
        unverified=[],
        generated_by="template",
        focal=focal,
        root=root,
        nodes=payload.nodes,
        seasonal_pct=payload.seasonal_pct,
        seasonal_query_id=payload.seasonal_query_id,
        no_confident_cause=False,
        redactions=payload.redactions,
        telemetry=payload.telemetry,
    )


def _connectivity(payload: NarrationPayload) -> tuple[str, str, str]:
    """Which sources are connected, which are simulated away, and which never existed.

    Read off the KPI's declared lineage rather than asserted in prose. The hardcoded
    version claimed "Connected sources: deploys (github)..." even while a simulation
    had disconnected github -- the card contradicting the scenario, in the one branch
    whose entire purpose is honesty about what we do not have.

    Returns (connected, not_connected, reconnect_target). `reconnect_target` is what
    the P1 should ask for: the dropped source when one is simulated, because that is a
    ticket somebody can close, and the standing gap otherwise.
    """
    from ledgerlens import contracts

    contract = contracts.CONTRACTS.get(payload.metric)
    steps = contract.lineage if contract else []
    evidence_sources = [s.source_system for s in steps if s.kind in ("context", "symptom")]

    live = [s for s in dict.fromkeys(evidence_sources) if s not in payload.drop_sources]
    dropped = [s for s in dict.fromkeys(evidence_sources) if s in payload.drop_sources]

    anticipated = contract.anticipated_event_types if contract else []
    never = [
        FEED_FOR_ANTICIPATED.get(e, f"a feed for {e}")
        for e in dict.fromkeys(anticipated)
    ]

    connected = ", ".join(SOURCE_LABEL.get(s, s) for s in live) or "none"
    parts = []
    if dropped:
        names = ", ".join(SOURCE_LABEL.get(s, s) for s in dropped)
        parts.append(f"{names} — simulated as disconnected for this run")
    parts.extend(never)
    not_connected = "; ".join(parts) or "nothing declared"

    reconnect = (
        ", ".join(dropped) if dropped else ", ".join(never) or "the missing systems"
    )
    return connected, not_connected, reconnect


def _no_cause_card(payload: NarrationPayload, who: personas.Persona) -> DiagnosisCard:
    """The honest branch. Nothing may paper over this -- "we cannot explain it from
    the connected sources" is a result, and naming the gap is the feature."""
    focal = payload.focal
    connected, not_connected, reconnect = _connectivity(payload)
    best = f" The closest candidate scored {payload.ranked[0].total:.2f}, below the {config.SCORE_FLOOR} floor." if payload.ranked else ""

    return DiagnosisCard(
        headline=(
            f"{payload.metric} in {cohort_label(focal.cohort)} down "
            f"{abs(focal.delta_pct):.0f}% -- no connected change explains it"
        ),
        summary=(
            f"The anomaly is real: {cohort_label(focal.cohort)} is {focal.delta_pct:.1f}% below "
            f"baseline ({_format_points(payload.metric, focal.delta_abs)}) over {focal.window.start} to {focal.window.end}."
            f"{best} No recorded change whose blast radius touches this cohort clears the "
            f"confidence floor. Connected sources: {connected}. "
            f"Not connected: {not_connected}. The cause may well sit in one of those."
            + _redaction_sentence(payload)
        ),
        causal_chain=[
            EvidenceStep(
                claim=f"{cohort_label(focal.cohort)} is {focal.delta_pct:.1f}% below baseline.",
                query_id=focal.query_id,
                observed=f"actual {_format_value(payload.metric, focal.actual)} vs expected {_format_value(payload.metric, focal.expected)}",
            )
        ],
        effect=None,
        ranked=payload.ranked,
        rejected=payload.rejected,
        open_question=None,
        actions=_for_persona(
            [
                Action(
                    priority="P1",
                    driver="no recorded change whose blast radius touches this cohort",
                    lever="connect_source",
                    action=(
                        f"Connect {reconnect} so the next incident of this shape has "
                        f"candidates to test."
                    ),
                    expected_impact=(
                        "Not quantified -- this raises candidate coverage for future "
                        "incidents. It does not itself recover revenue."
                    ),
                    owner=personas.OWNER_LABEL["data_platform"],
                    confidence=1.0,  # the absence of a candidate is directly observed
                    monitoring="Re-run this diagnosis after each new source lands.",
                    basis=f"no candidate above {config.SCORE_FLOOR} [{focal.query_id}]",
                )
            ],
            who,
        ),
        generated_by="template",
        focal=focal,
        root=payload.root,
        nodes=payload.nodes,
        seasonal_pct=payload.seasonal_pct,
        seasonal_query_id=payload.seasonal_query_id,
        no_confident_cause=True,
        redactions=payload.redactions,
        telemetry=payload.telemetry,
    )
