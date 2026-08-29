"""End-to-end orchestration.

A straight DAG: detect -> attribute -> gather symptoms -> generate candidates ->
score and control -> narrate. No agent framework, because there is no agency in it;
the only branch is "did anything clear the score floor".
"""

from __future__ import annotations

from datetime import date

import config
from ledgerlens import anomaly, hypothesis, narrate
from ledgerlens.ledger import symptoms as symptoms_mod
from ledgerlens.models import Anomaly, Cohort, DiagnosisCard, Window
from ledgerlens.store import Store

DEFAULT_AS_OF = date(2026, 8, 17)


def get_store(path=None) -> Store:
    """Open the database, loading from data/ the first time."""
    store = Store(path or config.DB_PATH)
    store.init_schema()
    n = store.con.execute("SELECT count(*) FROM fact_metric").fetchone()[0]
    if n == 0:
        store.load_all(config.DATA_DIR)
    return store


def diagnose(
    metric: str = "mrr_renewals",
    as_of: date = DEFAULT_AS_OF,
    store: Store | None = None,
    cohort: Cohort | None = None,
    window: Window | None = None,
) -> narrate.NarrationPayload | None:
    """Everything up to, but not including, prose. Returns None when there is no
    anomaly to explain.

    Split out from run() so a card can be rendered for several personas from ONE
    computation. That is what makes "identical evidence, different narrative" a
    structural property rather than a coincidence of determinism: persona lives
    strictly downstream of this function, so it cannot reach a query.
    """
    store = store or get_store()

    if cohort is not None and window is not None:
        ev, query_id = anomaly.measure(store, metric, cohort, window)
        if ev is None:
            return None
        root = anomaly._anomaly_from_eval(
            metric, cohort, window, window.start, ev, query_id, 1.0, 0, None
        )
        nodes = [root]
    else:
        root = anomaly.detect(store, metric, as_of)
        if root is None:
            return None
        nodes = anomaly.drill(store, root, config.DRILL_DIMS)

    focal = anomaly.focal(nodes)
    symptoms = symptoms_mod.cluster(store, focal.window)
    hyps = hypothesis.rank(store, focal, symptoms)

    ranked = [h for h in hyps if h.rejection_reason is None]
    rejected = [h for h in hyps if h.rejection_reason is not None]

    seasonal_pct, seasonal_query_id = anomaly.seasonal_estimate(store, metric, root.cohort)

    return narrate.NarrationPayload(
        metric=metric,
        root=root,
        focal=focal,
        nodes=nodes,
        ranked=ranked,
        rejected=rejected,
        symptoms=symptoms,
        seasonal_pct=seasonal_pct,
        seasonal_query_id=seasonal_query_id,
        no_confident_cause=not ranked or ranked[0].total < config.SCORE_FLOOR,
    )


def run(
    metric: str = "mrr_renewals",
    as_of: date = DEFAULT_AS_OF,
    store: Store | None = None,
    cohort: Cohort | None = None,
    window: Window | None = None,
) -> DiagnosisCard:
    """Diagnose `metric` as of `as_of`.

    Passing `cohort`/`window` bypasses detection entirely. Detection is advisory, not
    gating: every blind spot it has (slow drifts, ratio metrics, interaction effects,
    offsetting moves that cancel at the root) becomes "we don't auto-surface this"
    rather than "we can't diagnose this", because the downstream chain does not care
    where the focal anomaly came from.
    """
    payload = diagnose(metric, as_of, store=store, cohort=cohort, window=window)
    if payload is None:
        return DiagnosisCard.no_anomaly(metric, as_of)
    return narrate.narrate(payload)


def card_query_ids(card: DiagnosisCard) -> list[str]:
    """Every query id reachable from a finished card, for the provenance audit."""
    ids: list[str] = [s.query_id for s in card.causal_chain]
    if card.seasonal_query_id:
        ids.append(card.seasonal_query_id)
    for node in card.nodes:
        ids.append(node.query_id)
    for h in card.ranked + card.rejected:
        ids.extend(h.query_ids)
        ids.extend(c.query_id for c in h.controls)
        ids.extend(s.query_id for s in h.symptoms if s.query_id)
    return sorted({i for i in ids if i})


def _print(card: DiagnosisCard) -> None:
    line = "=" * 78
    print(f"\n{line}\n{card.headline}\n{line}\n")
    print(card.summary, "\n")
    print("EVIDENCE")
    for i, step in enumerate(card.causal_chain, 1):
        print(f"  {i}. {step.claim}")
        print(f"     -> {step.observed}   [{step.query_id}]")
    print("\nRANKED")
    for i, h in enumerate(card.ranked, 1):
        s = h.scores
        print(
            f"  #{i} {h.event.event_id:<24} {h.total:.3f}  "
            f"T={s.T:.2f} C={s.C:.2f} D={s.D:.2f} N={s.N:.2f} P={s.P:.2f}"
        )
    if card.rejected:
        print("\nREJECTED")
        for h in card.rejected:
            print(f"  x  {h.event.event_id:<24} {h.total:.3f}  {h.rejection_reason}")
    print("\nACTIONS")
    for a in card.actions:
        print(f"  [{a.priority}] {a.owner}: {a.action}")
        print(f"        basis: {a.basis}")
    print()


if __name__ == "__main__":
    _print(run())
