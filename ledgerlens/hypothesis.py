"""Candidate generation and the five-component scorer.

No component is an LLM opinion. All five are reproducible queries, and the weights
are printed on the hypothesis card rather than hidden as a hyperparameter -- which is
the answer to "how is this not hallucination?".
"""

from __future__ import annotations

import math
from datetime import timedelta

import numpy as np
from scipy import stats

import config
from ledgerlens import controls as controls_mod
from ledgerlens import learning
from ledgerlens.models import (
    Anomaly,
    ChangeEvent,
    Cohort,
    ComponentScores,
    Hypothesis,
    SymptomCluster,
    cohort_intersect,
    stable_id,
)
from ledgerlens.store import Store


def candidates(
    store: Store, a: Anomaly, drop_sources: frozenset[str] = frozenset()
) -> list[ChangeEvent]:
    """Events that both PRECEDE the anomaly and could plausibly TOUCH it.

    Two filters, both cheap and both deterministic: a time window, then a cohort
    intersection. The US pricing change dies here -- region US against region DACH is
    the empty set, so it never becomes a candidate at all, let alone a ranked one.

    `drop_sources` simulates a source system that is not connected. It is applied HERE,
    at candidate generation, rather than as a score penalty later -- because an
    unconnected system does not produce a badly-scoring candidate, it produces no rows
    at all. Filtering at any later stage would model a different and less honest
    scenario: one where we saw the change and dismissed it.
    """
    lo = a.onset - timedelta(days=config.LOOKBACK_DAYS)
    out = []
    for ev in store.events():
        if ev.source in drop_sources:
            continue
        ts = ev.ts_start.date()
        if ts < lo or ts > a.window.end:
            continue
        if cohort_intersect(ev.blast_radius, a.cohort) is None:
            continue
        out.append(ev)
    return out


# ------------------------------------------------------------------ components


def temporal(a: Anomaly, ev: ChangeEvent) -> float:
    """T -- did it start just before the metric broke?"""
    lag = (a.onset - ev.ts_start.date()).days
    if lag < 0:
        return 0.0  # an event after onset cannot have caused it
    score = 1.0 if lag == 0 else math.exp(-lag / 3.0)
    if ev.ts_end is not None and ev.ts_end.date() < a.onset:
        score *= 0.3  # already reverted before the drop began
    return score


def cohort_match(store: Store, a: Anomaly, ev: ChangeEvent) -> tuple[float, list[str]]:
    """C -- Jaccard over the ROWS each predicate selects, not over the predicates.

    This is what beats the marketing decoy. The campaign covers all of DACH (every
    segment, every rail); the anomaly is DACH x Enterprise x SEPA. Comparing rows
    rather than dimension labels is what makes a region-wide radius score badly
    against a rail-and-segment-specific anomaly instead of scoring a flat "region
    matches".
    """
    inter = cohort_intersect(a.cohort, ev.blast_radius)
    n_a, q_a = store.cohort_rows(a.cohort, a.window, a.metric)
    n_b, q_b = store.cohort_rows(ev.blast_radius, a.window, a.metric)
    if inter is None:
        return 0.0, [q_a, q_b]
    n_i, q_i = store.cohort_rows(inter, a.window, a.metric)
    union = n_a + n_b - n_i
    return (n_i / union if union else 0.0), [q_a, q_b, q_i]


def dose_response(store: Store, a: Anomaly, ev: ChangeEvent) -> float:
    """D -- do more-exposed sub-cohorts hurt more?

    Returns the uninformative 0.5 when the question does not apply. For this incident
    it always does: both candidate blast radii fully contain the focal cohort, so
    every sub-slice has exposure 1.0, the exposure vector has no variance, and a rank
    correlation is undefined. Reporting 0.5 rather than inventing a number is the
    point -- the ranking here is carried by C and N, and we say so.
    """
    from ledgerlens import anomaly as anomaly_mod

    inter = cohort_intersect(a.cohort, ev.blast_radius)
    if inter is None:
        return 0.5

    best: tuple[float, list[float], list[float]] | None = None
    for dim in [d for d in config.DRILL_DIMS if d not in inter]:
        exposure, impact = [], []
        for value in store.dim_universe(dim):
            sub = {**inter, dim: [value]}
            rows, _ = store.cohort_rows(sub, a.window, a.metric)
            if rows == 0:
                continue
            inside = cohort_intersect(sub, ev.blast_radius)
            n_in = store.cohort_rows(inside, a.window, a.metric)[0] if inside else 0
            sub_eval, _ = anomaly_mod.measure(store, a.metric, sub, a.window)
            if sub_eval is None:
                continue
            exposure.append(n_in / rows)
            impact.append(-sub_eval.delta_pct)
        if len(exposure) >= 3:
            var = float(np.var(exposure))
            if best is None or var > best[0]:
                best = (var, exposure, impact)

    if best is None:
        return 0.5
    _, exposure, impact = best
    if len(exposure) < 3 or np.std(exposure) == 0 or np.std(impact) == 0:
        return 0.5
    rho = stats.spearmanr(exposure, impact).statistic
    return max(0.0, float(rho)) if np.isfinite(rho) else 0.5


def attach_symptoms(
    ev: ChangeEvent, a: Anomaly, symptoms: list[SymptomCluster]
) -> list[SymptomCluster]:
    """Corroborating evidence, deliberately kept OUT of the score.

    Symptom volume and cohort fit measure the same signal C already measures, so
    scoring both would double-count it. They are narrative support, not a component.
    """
    lo, hi = a.onset - timedelta(days=1), a.onset + timedelta(days=3)
    return [
        c
        for c in symptoms
        if cohort_intersect(c.cohort, ev.blast_radius) is not None and lo <= c.first_seen <= hi
    ]


# --------------------------------------------------------------------- scoring


def score(
    store: Store, a: Anomaly, ev: ChangeEvent, symptoms: list[SymptomCluster] | None = None
) -> Hypothesis:
    symptoms = symptoms or []
    ctrls = controls_mod.generate(store, a, ev)
    n_score, rejection = controls_mod.score_n(ctrls)
    c_score, c_queries = cohort_match(store, a, ev)
    p_score, p_query = learning.prior(store, ev.event_type, a.metric)

    scores = ComponentScores(
        T=round(temporal(a, ev), 6),
        C=round(c_score, 6),
        D=round(dose_response(store, a, ev), 6),
        N=round(n_score, 6),
        P=round(p_score, 6),
    )
    # LLM-extracted events carry their extraction confidence into the ranking, and
    # the UI badges them "inferred -- verify". Deterministic events are unaffected.
    total = scores.total(config.SCORE_WEIGHTS) * ev.confidence

    return Hypothesis(
        hypothesis_id=stable_id("h", a.anomaly_id, ev.event_id),
        anomaly_id=a.anomaly_id,
        event=ev,
        scores=scores,
        total=round(total, 6),
        controls=ctrls,
        symptoms=attach_symptoms(ev, a, symptoms),
        rejection_reason=rejection,
        # p_query is last and may be empty (no store -> no prior query). Filtered
        # here rather than by the consumer, so nothing downstream has to know that the
        # prior is the one component that can be computed without a query.
        query_ids=[
            q for q in [a.query_id, *c_queries, *[c.query_id for c in ctrls], p_query] if q
        ],
    )


def rank(
    store: Store,
    a: Anomaly,
    symptoms: list[SymptomCluster] | None = None,
    drop_sources: frozenset[str] = frozenset(),
) -> list[Hypothesis]:
    hyps = [score(store, a, ev, symptoms) for ev in candidates(store, a, drop_sources)]
    return sorted(hyps, key=lambda h: (-h.total, h.event.event_id))
