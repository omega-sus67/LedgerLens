"""End-to-end orchestration.

A straight DAG: detect -> attribute -> gather symptoms -> generate candidates ->
score and control -> narrate. No agent framework, because there is no agency in it;
the only branch is "did anything clear the score floor".
"""

from __future__ import annotations

import time
from datetime import date

import config
from ledgerlens import anomaly, contracts, hypothesis, investigator, llm, narrate, personas
from ledgerlens.ledger import symptoms as symptoms_mod
from ledgerlens.models import Anomaly, Cohort, DiagnosisCard, Redaction, Telemetry, Window
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


class _Stopwatch:
    """Stage timings for one diagnosis.

    A small class rather than perf_counter pairs scattered through diagnose(), so the
    stage names live in one place and a branch that SKIPS a stage simply never records
    it. Padding the dict with 0.0 for a stage that never ran would read as "instant"
    rather than "not applicable" -- see docs/telemetry_decisions.md D4.
    """

    def __init__(self) -> None:
        self.stage_ms: dict[str, float] = {}
        self._t0 = time.perf_counter()

    def time(self, stage: str, fn):
        """try/finally, not try/except: the timing is recorded even when the stage
        raises, and the exception still propagates. Do not convert this to except."""
        start = time.perf_counter()
        try:
            return fn()
        finally:
            self.stage_ms[stage] = (time.perf_counter() - start) * 1000

    @property
    def total_ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000


def _contract_for_engine(metric: str) -> contracts.KpiContract | None:
    """LENIENT lookup, matching `contracts.thresholds`.

    The UI refuses to render an ungoverned KPI (`contracts.get` raises); the engine
    must degrade to global defaults rather than crash. Detection is not the place a
    governance gap should surface, so the strict lookup does not belong on this path.
    """
    return contracts.CONTRACTS.get(metric)


def _visible_dims(metric: str, role: str | None) -> list[str]:
    """The dimensions this role may drill into.

    Entitlement is enforced HERE and nowhere else -- one chokepoint, so there is no
    second place for the policy to be forgotten. `role=None` means unrestricted and
    returns the global list unchanged, which is what keeps every existing call site
    byte-identical.
    """
    contract = _contract_for_engine(metric)
    if role is None or contract is None:
        return config.DRILL_DIMS
    return contract.visible_drill_dims(role)


def _redactions_for(metric: str, role: str | None) -> list[Redaction]:
    """What policy withheld, read off the contract.

    Never inferred by diffing against DRILL_DIMS: a redaction with no declared policy
    behind it is exactly the unattributable refusal this feature exists to avoid.
    """
    contract = _contract_for_engine(metric)
    if role is None or contract is None:
        return []
    return [
        Redaction(dim=dim, policy_id=rule.policy_id, reason=rule.reason)
        for rule in contract.access
        if rule.role == role
        for dim in rule.hidden_dims
    ]


def diagnose(
    metric: str = "mrr_renewals",
    as_of: date = DEFAULT_AS_OF,
    store: Store | None = None,
    cohort: Cohort | None = None,
    window: Window | None = None,
    role: str | None = None,
    drop_sources: frozenset[str] = frozenset(),
    investigate: bool = False,
) -> narrate.NarrationPayload | None:
    """Everything up to, but not including, prose. Returns None when there is no
    anomaly to explain.

    Split out from run() so a card can be rendered for several personas from ONE
    computation. That is what makes "identical evidence, different narrative" a
    structural property rather than a coincidence of determinism: persona lives
    strictly downstream of this function, so it cannot reach a query.

    `role` is the exception that proves that rule. Entitlement is NOT a rendering
    concern: hiding a dimension changes which cuts are drilled, so it changes the
    focal cohort and therefore the numbers. It must enter here, above the caching
    boundary, and `app.py`'s cache key must include it.

    `drop_sources` is the same shape again: simulating a disconnected source removes
    candidates, which changes the answer. It joins the cache key too.

    `investigate` is the FOURTH such input, exactly as this docstring predicted when
    task 7 added the third. It turns on the LLM investigator lane
    (docs/ai_decisions.md). It is above the payload boundary because the lane runs
    queries and puts their results on the card -- but note what it still cannot do:
    every figure it adds is additive, and none of it reaches `hypothesis.rank` or
    `controls.score_n`, so the ranked order and every score are identical with it on
    or off. `tests/test_investigator.py` asserts that.
    """
    store = store or get_store()
    watch = _Stopwatch()
    stats_before = store.stats_snapshot()

    if cohort is not None and window is not None:
        ev, query_id = watch.time(
            "measure", lambda: anomaly.measure(store, metric, cohort, window)
        )
        if ev is None:
            return None
        root = anomaly._anomaly_from_eval(
            metric, cohort, window, window.start, ev, query_id, 1.0, 0, None
        )
        nodes = [root]
    else:
        root = watch.time("detect", lambda: anomaly.detect(store, metric, as_of))
        if root is None:
            return None
        nodes = watch.time(
            "drill", lambda: anomaly.drill(store, root, _visible_dims(metric, role))
        )

    focal = anomaly.focal(nodes)
    symptoms = watch.time("symptoms", lambda: symptoms_mod.cluster(store, focal.window))
    hyps = watch.time(
        "rank", lambda: hypothesis.rank(store, focal, symptoms, drop_sources)
    )

    ranked = [h for h in hyps if h.rejection_reason is None]
    rejected = [h for h in hyps if h.rejection_reason is not None]

    seasonal_pct, seasonal_query_id = watch.time(
        "seasonal", lambda: anomaly.seasonal_estimate(store, metric, root.cohort)
    )

    # ---- the investigator lane. Everything above this line is deterministic and
    # stays deterministic; everything below is additive and fails open.
    #
    # It runs AFTER ranking on purpose: the model is shown the engine's conclusions
    # and the controls already run, so it proposes checks that ATTACK them rather
    # than re-deriving them. A lane that ran first would be guessing.
    budget = llm.Budget()
    proposed: list = []
    rejections: list[str] = []
    unverified: list = []
    provider = llm.resolve()[0] if investigate else None
    if provider is not None:
        proposed, rejections = watch.time(
            "propose",
            lambda: investigator.propose_tests(store, focal, ranked, budget, provider),
        )
        unverified = watch.time(
            "unverified",
            lambda: investigator.unverified_causes(
                store, focal, ranked, _contract_for_engine(metric), drop_sources, budget, provider
            ),
        )

    stats_after = store.stats_snapshot()

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
        redactions=_redactions_for(metric, role),
        drop_sources=drop_sources,
        proposed_tests=proposed,
        unverified=unverified,
        proposal_rejections=rejections,
        llm_budget=budget if investigate else None,
        llm_narration=investigate,
        telemetry=Telemetry(
            stage_ms=watch.stage_ms,
            total_ms=watch.total_ms,
            queries_executed=stats_after["executed"] - stats_before["executed"],
            queries_cached=stats_after["cached"] - stats_before["cached"],
        ),
    )


def run(
    metric: str = "mrr_renewals",
    as_of: date = DEFAULT_AS_OF,
    store: Store | None = None,
    cohort: Cohort | None = None,
    window: Window | None = None,
    role: str | None = None,
    persona: "personas.Persona | None" = None,
    drop_sources: frozenset[str] = frozenset(),
    investigate: bool = False,
) -> DiagnosisCard:
    """Diagnose `metric` as of `as_of`.

    Passing `cohort`/`window` bypasses detection entirely. Detection is advisory, not
    gating: every blind spot it has (slow drifts, ratio metrics, interaction effects,
    offsetting moves that cancel at the root) becomes "we don't auto-surface this"
    rather than "we can't diagnose this", because the downstream chain does not care
    where the focal anomaly came from.

    `role` and `persona` are the two halves of "who is reading this", and they are
    NOT the same thing: role decides what may be computed, persona decides how it is
    told. Role changes the numbers; persona never does.
    """
    payload = diagnose(
        metric,
        as_of,
        store=store,
        cohort=cohort,
        window=window,
        role=role,
        drop_sources=drop_sources,
        investigate=investigate,
    )
    if payload is None:
        return DiagnosisCard.no_anomaly(metric, as_of)
    return narrate.narrate(payload, persona=persona)


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
    # An AI-proposed check that executed carries a real query_id and is replayable
    # exactly like a rule-based control, so it counts as auditable. A no-op when the
    # investigator lane is off, which is why no existing telemetry number moves.
    ids.extend(t.result.query_id for t in card.proposed_tests if t.result)
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
