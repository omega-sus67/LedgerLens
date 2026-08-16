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


def _money(x: float) -> str:
    return f"{'-' if x < 0 else ''}${abs(x):,.0f}"


def narrate(payload: NarrationPayload, no_confident_cause: bool = False) -> DiagnosisCard:
    if no_confident_cause or not payload.ranked:
        return _no_cause_card(payload)
    return _cause_card(payload)


def _unexplained(payload: NarrationPayload) -> float:
    """Residual after the calendar is accounted for: (1+observed)/(1+seasonal) - 1."""
    observed = payload.root.delta_pct / 100
    seasonal = payload.seasonal_pct / 100
    return 100 * ((1 + observed) / (1 + seasonal) - 1)


def _cause_card(payload: NarrationPayload) -> DiagnosisCard:
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

    owner = OWNER_BY_SOURCE.get(top.event.source, "the change owner")
    actions = [
        Action(
            priority="P0",
            owner=owner,
            action=(
                f"Roll back or hotfix {top.event.event_id} for {cohort_label(top.event.blast_radius)}, "
                f"then re-run this diagnosis to confirm recovery."
            ),
            basis=f"{_money(focal.delta_abs)} shortfall over {focal.window.days} days [{focal.query_id}]",
        ),
        Action(
            priority="P1",
            owner="revenue operations",
            action=(
                f"Hold the {cohort_label({k: v for k, v in focal.cohort.items() if k == 'region'})} "
                f"renewals forecast until the rail recovers; treat the shortfall as at-risk, "
                f"not lost."
            ),
            basis=f"focal cohort actual {_money(focal.actual)} vs expected {_money(focal.expected)} [{focal.query_id}]",
        ),
    ]
    for rejected in payload.rejected:
        objective = next(
            (c for c in rejected.controls if c.rule == "R4 objective-mismatch" and c.passed), None
        )
        if objective is not None:
            actions.append(
                Action(
                    priority="P2",
                    owner=OWNER_BY_SOURCE.get(rejected.event.source, "the change owner"),
                    action=(
                        f"Separately: {rejected.event.event_id} did not cause this, but it is "
                        f"doing what it was designed to do to {objective.metric}. Confirm that "
                        f"trade-off is intended."
                    ),
                    basis=f"{objective.metric} {objective.observed_delta_pct:+.1f}% in "
                    f"{cohort_label(objective.cohort)} [{objective.query_id}]",
                )
            )

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


def _no_cause_card(payload: NarrationPayload) -> DiagnosisCard:
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
        actions=[
            Action(
                priority="P1",
                owner="data platform",
                action=f"Connect {missing} so the next incident of this shape has candidates to test.",
                basis=f"no candidate above {config.SCORE_FLOOR} [{focal.query_id}]",
            )
        ],
        generated_by="template",
        focal=focal,
        root=payload.root,
        nodes=payload.nodes,
        seasonal_pct=payload.seasonal_pct,
        seasonal_query_id=payload.seasonal_query_id,
        no_confident_cause=True,
    )
