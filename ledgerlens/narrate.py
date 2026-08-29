"""Narration.

This is the TEMPLATE branch, which is what runs in tests and on stage. It is written
first and treated as the product; an LLM narrator is an upgrade that swaps the prose,
never the numbers.

Nothing in here computes anything. Every figure is copied from an upstream object
that already carries a query_id, which is what makes each claim clickable back to the
SQL that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass

import config
from ledgerlens import personas
from ledgerlens.models import (
    Action,
    Anomaly,
    DiagnosisCard,
    EvidenceStep,
    Hypothesis,
    SymptomCluster,
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


def _money(x: float) -> str:
    return f"{'-' if x < 0 else ''}${abs(x):,.0f}"


def narrate(
    payload: NarrationPayload,
    persona: personas.Persona | None = None,
    no_confident_cause: bool | None = None,
) -> DiagnosisCard:
    who = persona or personas.get(personas.DEFAULT_PERSONA_ID)
    abstain = payload.no_confident_cause if no_confident_cause is None else no_confident_cause
    if abstain or not payload.ranked:
        return _no_cause_card(payload, who)
    return _cause_card(payload, who)


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

    if who.persona_id == "cfo":
        headline = (
            f"{_metric_label(payload.metric)}: {_money(abs(root.delta_abs))} below "
            f"plan for {root.window.start} to {root.window.end}"
        )
        summary = (
            f"{_metric_label(payload.metric)} came in {_money(abs(root.delta_abs))} "
            f"({root.delta_pct:.1f}%) under baseline for {root.window.start} to "
            f"{root.window.end}. About {abs(payload.seasonal_pct):.1f} points of that is "
            f"normal August seasonality. The remaining {abs(unexplained):.1f} points sit "
            f"almost entirely in one customer group -- {cohort} -- which is "
            f"{_money(focal.delta_abs)} short against its own baseline. "
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
            f"{top.event.event_id} ({top.event.description}) went out "
            f"{top.event.ts_start:%Y-%m-%d %H:%M}. Declared blast radius: "
            f"{cohort_label(top.event.blast_radius)}. {payload.metric} in {cohort} is "
            f"{focal.delta_pct:.0f}% below baseline from {focal.window.start}, "
            f"{_money(focal.delta_abs)} over {focal.window.days} days. "
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
            f"{payload.metric} in {cohort} is {focal.delta_pct:.0f}% below baseline "
            f"({_money(focal.delta_abs)}). {rejected_line}"
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
        f"{payload.metric} is {root.delta_pct:.1f}% below baseline for "
        f"{root.window.start} to {root.window.end}. Roughly {payload.seasonal_pct:.1f}% of that "
        f"is August seasonality; the remaining {unexplained:.1f}% concentrates almost entirely "
        f"in {cohort}, which is down {focal.delta_pct:.0f}% and {_money(focal.delta_abs)} against "
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
                f"Recovers up to {_money(abs(focal.delta_abs))} of the {focal.window.days}-day "
                f"shortfall if the rollback restores the cohort to its own baseline."
            ),
            owner=owner,
            confidence=top.total,
            monitoring=(
                f"Re-run this diagnosis daily. {cohort} back within "
                f"{config.CONTROL_PASS_BAND_PCT:.0f}% of baseline within 3 days, or escalate."
            ),
            basis=f"{_money(focal.delta_abs)} shortfall over {focal.window.days} days [{focal.query_id}]",
        ),
        Action(
            priority="P1",
            driver=driver,
            lever="hold_forecast",
            action=(
                f"Hold the {cohort_label({k: v for k, v in focal.cohort.items() if k == 'region'})} "
                f"renewals forecast until the rail recovers; treat the shortfall as at-risk, "
                f"not lost."
            ),
            expected_impact=(
                f"Reclassifies {_money(abs(focal.delta_abs))} from lost to at-risk in the "
                f"current forecast. No revenue effect on its own."
            ),
            owner=personas.OWNER_LABEL["revops"],
            confidence=top.total,
            monitoring=(
                f"Release the hold after the cohort sits within "
                f"{config.CONTROL_PASS_BAND_PCT:.0f}% of baseline for 3 consecutive days."
            ),
            basis=f"focal cohort actual {_money(focal.actual)} vs expected {_money(focal.expected)} [{focal.query_id}]",
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
            observed=f"actual {_money(root.actual)} vs expected {_money(root.expected)}",
        ),
        EvidenceStep(
            claim=(
                f"About {payload.seasonal_pct:.1f}% of that is ordinary August seasonality, "
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
            observed=f"shortfall {_money(focal.delta_abs)} (z = {focal.residual_z:.1f})",
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
    )


def _no_cause_card(payload: NarrationPayload, who: personas.Persona) -> DiagnosisCard:
    """The honest branch. Nothing may paper over this -- "we cannot explain it from
    the connected sources" is a result, and naming the gap is the feature."""
    focal = payload.focal
    connected = "deploys (github), feature flags (launchdarkly), campaigns (calendar), pricing (pricing_db), support tickets (zendesk)"
    missing = "CRM/opportunity data, competitor pricing, macroeconomic indicators, vendor status feeds"
    best = f" The closest candidate scored {payload.ranked[0].total:.2f}, below the {config.SCORE_FLOOR} floor." if payload.ranked else ""

    return DiagnosisCard(
        headline=(
            f"{payload.metric} in {cohort_label(focal.cohort)} down "
            f"{abs(focal.delta_pct):.0f}% -- no connected change explains it"
        ),
        summary=(
            f"The anomaly is real: {cohort_label(focal.cohort)} is {focal.delta_pct:.1f}% below "
            f"baseline ({_money(focal.delta_abs)}) over {focal.window.start} to {focal.window.end}."
            f"{best} No recorded change whose blast radius touches this cohort clears the "
            f"confidence floor. Connected sources: {connected}. Not connected: {missing}. "
            f"The cause may well sit in one of those."
        ),
        causal_chain=[
            EvidenceStep(
                claim=f"{cohort_label(focal.cohort)} is {focal.delta_pct:.1f}% below baseline.",
                query_id=focal.query_id,
                observed=f"actual {_money(focal.actual)} vs expected {_money(focal.expected)}",
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
                        f"Connect {missing} so the next incident of this shape has "
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
    )
