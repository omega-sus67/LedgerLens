"""Negative control generation and evaluation -- the credibility layer.

For each candidate we construct the cohorts its blast radius says should be
UNAFFECTED and check that they were, plus the cohorts a rival mechanism says should
ALSO have moved and check whether they did. This is the honest, N=1-appropriate
replacement for a causal-inference library's refuters: it needs no DAG, no
distributional assumption, and every control is a query an analyst can re-run.

It is also what kills the marketing decoy on camera.
"""

from __future__ import annotations

from datetime import timedelta

import config
from ledgerlens.models import (
    Anomaly,
    ChangeEvent,
    ControlResult,
    Window,
    canonical_cohort_key,
    cohort_complement,
    cohort_label,
)
from ledgerlens.store import Store


def decisive_failure(cr: ControlResult) -> bool:
    """A failure severe enough to reject the hypothesis outright, not just lower N.

    SPEC-GAP (bug A): spec 9.2 triggers rejection only on a failing `should_be_flat`
    control. But the control that kills the marketing decoy is a `should_also_drop`
    control that failed by staying FLAT -- so as literally specified the decoy keeps
    N = 4/5, is never rejected, and the phase-6 acceptance test cannot pass. Both
    directions are decisive; they just fail in opposite ways.
    """
    if cr.prediction == "should_be_flat":
        # moved hard, in the same direction as the anomaly -> the "unaffected"
        # cohort was affected, so the proposed mechanism cannot be what happened
        return cr.observed_delta_pct <= -config.CONTROL_PASS_BAND_PCT
    # predicted to fall with the anomaly and simply did not
    return cr.observed_delta_pct >= config.DECISIVE_FLAT_PCT


def _evaluate(
    store: Store,
    metric: str,
    cohort: dict,
    window: Window,
    prediction: str,
    name: str,
    rule: str,
) -> ControlResult | None:
    from ledgerlens import anomaly as anomaly_mod

    if not cohort or any(not v for v in cohort.values()):
        return None
    ev, query_id = anomaly_mod.measure(store, metric, cohort, window)
    if ev is None:
        return None
    delta = ev.delta_pct
    passed = (
        abs(delta) < config.CONTROL_PASS_BAND_PCT
        if prediction == "should_be_flat"
        else delta < -config.CONTROL_PASS_BAND_PCT
    )
    result = ControlResult(
        name=name,
        cohort=cohort,
        metric=metric,
        prediction=prediction,
        observed_delta_pct=round(delta, 3),
        passed=passed,
        query_id=query_id,
        rule=rule,
    )
    return result.model_copy(update={"decisive": (not passed) and decisive_failure(result)})


def generate(store: Store, a: Anomaly, ev: ChangeEvent) -> list[ControlResult]:
    out: list[ControlResult] = []
    universe = {d: store.dim_universe(d) for d in config.DRILL_DIMS}

    # --- Rule 1: dimension complement.
    # For each dimension the event constrains and the anomaly also constrains, flip
    # it. If the SEPA connector broke, DACH Enterprise CARD renewals should be flat.
    for dim in sorted(set(ev.blast_radius) & set(a.cohort)):
        siblings = set(universe.get(dim, [])) - set(a.cohort[dim])
        if not siblings:
            continue
        cohort = cohort_complement(a.cohort, dim, universe[dim])
        out.append(
            _evaluate(
                store,
                a.metric,
                cohort,
                a.window,
                "should_be_flat",
                f"{cohort_label(cohort)} ({a.metric})",
                f"R1 {dim}-complement",
            )
        )

    # --- Rule 2: segment siblings.
    # SPEC-GAP (bug B): spec 9.4 fires this for ANY event leaving `segment`
    # unconstrained -- which includes the true cause, whose radius is
    # {region, payment_rail}. It would build this same control, find it flat, and
    # reject the real answer. So it is gated on mechanism class: a demand-side change
    # to a region has no mechanism by which it could spare Mid/SMB customers in that
    # region, whereas a deploy targets a CODE PATH -- and enterprise direct debit is
    # a distinct code path. This is the most load-bearing assumption in the module.
    if (
        ev.event_type in config.SEGMENT_AGNOSTIC_EVENT_TYPES
        and "segment" not in ev.blast_radius
        and "segment" in a.cohort
    ):
        cohort = cohort_complement(a.cohort, "segment", universe["segment"])
        out.append(
            _evaluate(
                store,
                a.metric,
                cohort,
                a.window,
                "should_also_drop",
                f"{cohort_label(cohort)} ({a.metric})",
                "R2 segment-siblings",
            )
        )

    # --- Rule 3: geographic complement, segment-relaxed.
    # SPEC-GAP (bug C): spec 9.4's rule 3 as written is byte-identical to rule 1 with
    # dim=region, so it dedupes away and leaves the true cause with only two controls
    # against the "passes >= 3" acceptance bar. Relaxing `segment` makes it a
    # genuinely different question: did the rail break anywhere else at all?
    if "region" in ev.blast_radius:
        cohort = {
            "region": sorted(set(universe["region"]) - set(ev.blast_radius["region"]))
        }
        if "payment_rail" in a.cohort:
            cohort["payment_rail"] = a.cohort["payment_rail"]
        out.append(
            _evaluate(
                store,
                a.metric,
                cohort,
                a.window,
                "should_be_flat",
                f"{cohort_label(cohort)} ({a.metric}, all segments)",
                "R3 geo-complement",
            )
        )

    # --- Rule 4: objective mismatch.
    # A campaign targets acquisition, so test the metric it was actually aimed at.
    # This is what surfaces the honest second finding: the budget cut DID cause a
    # real ~30% new-logo drop -- just not the renewals anomaly we are diagnosing.
    if ev.event_type == "campaign":
        other = "new_logo_bookings"
        out.append(
            _evaluate(
                store,
                other,
                dict(ev.blast_radius),
                a.window,
                "should_also_drop",
                f"{cohort_label(ev.blast_radius)} ({other})",
                "R4 objective-mismatch",
            )
        )

    # --- Rule 5: temporal placebo.
    # SPEC-GAP: added with rule 3. The same cohort, one cycle earlier: if it looks
    # broken there too, we are measuring a fitting artefact rather than an incident.
    shift = timedelta(days=config.PLACEBO_SHIFT_DAYS)
    out.append(
        _evaluate(
            store,
            a.metric,
            dict(a.cohort),
            Window(start=a.window.start - shift, end=a.window.end - shift),
            "should_be_flat",
            f"{cohort_label(a.cohort)}, {config.PLACEBO_SHIFT_DAYS}d earlier (placebo)",
            "R5 temporal-placebo",
        )
    )

    seen = set()
    deduped = []
    for c in out:
        if c is None:
            continue
        key = (c.metric, canonical_cohort_key(c.cohort), c.prediction)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    return deduped


def score_n(controls: list[ControlResult]) -> tuple[float, str | None]:
    """N = fraction passed, unless a control failed decisively -- then it is zero.

    A decisive failure cannot be outvoted by passing controls: if the mechanism
    predicts something that plainly did not happen, the other checks agreeing is not
    evidence for it.
    """
    if not controls:
        return 0.5, None
    for c in controls:
        if c.decisive:
            direction = "stayed flat" if c.prediction == "should_also_drop" else "dropped too"
            return 0.0, (
                f"Control '{c.name}' predicted {c.prediction.replace('_', ' ')}; "
                f"it {direction} at {c.observed_delta_pct:+.1f}%"
            )
    return sum(c.passed for c in controls) / len(controls), None


def best_flat_control(controls: list[ControlResult]) -> ControlResult | None:
    passing = [c for c in controls if c.passed and c.prediction == "should_be_flat"]
    return passing[0] if passing else None
