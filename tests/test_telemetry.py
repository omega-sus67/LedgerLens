"""Runtime telemetry: latency, database work, model calls, tokens, cost.

Closes MPE rows 9 (LLM vs non-LLM breakdown) and 10 (runtime telemetry). The zero in
the LLM column is the product's strongest single claim, so it is asserted here rather
than merely printed.

Every assertion in this file is about STRUCTURE or about ZERO. None is about a
duration: `Store._q_cache` makes a warm run ~2.6x faster than a cold one, and the
session-scoped `store` fixture is warm in an order-dependent way. A millisecond bound
here would flake. See docs/telemetry_decisions.md D7.
"""

from __future__ import annotations

from datetime import date

import config
from ledgerlens import narrate, personas, pipeline
from ledgerlens.models import DiagnosisCard, Telemetry, Window
from ledgerlens.store import Store

DETECT_STAGES = {"detect", "drill", "symptoms", "rank", "seasonal"}
MANUAL_STAGES = {"measure", "symptoms", "rank", "seasonal"}


# ------------------------------------------------------------- 6.1 model + counter


def test_telemetry_defaults_to_none_on_a_card_with_no_pipeline_behind_it():
    card = DiagnosisCard.no_anomaly("mrr_renewals", pipeline.DEFAULT_AS_OF)
    assert card.telemetry is None


def test_telemetry_model_defaults_the_llm_columns_to_zero():
    t = Telemetry(
        stage_ms={"detect": 1.0},
        total_ms=1.0,
        queries_executed=1,
        queries_cached=0,
        queries_on_card=0,
    )
    assert (t.llm_calls, t.llm_tokens, t.llm_cost_usd) == (0, 0, 0.0)


def test_store_counts_executed_and_cached_separately(tmp_path):
    """The three query counts are three different numbers. A cache hit does no
    database work and must not be billed as if it did."""
    s = Store(tmp_path / "t.duckdb")
    s.init_schema()
    before = s.stats_snapshot()
    s.q("SELECT 1 AS a")
    s.q("SELECT 1 AS a")  # identical -> cache hit
    after = s.stats_snapshot()
    assert after["issued"] - before["issued"] == 2
    assert after["executed"] - before["executed"] == 1
    assert after["cached"] - before["cached"] == 1
    s.close()


def test_stats_snapshot_is_a_copy_not_a_live_view(tmp_path):
    """A caller holds a snapshot across a whole diagnosis to compute a delta. If it
    were the live dict, the 'before' would move with the 'after' and every delta
    would be zero."""
    s = Store(tmp_path / "t2.duckdb")
    s.init_schema()
    before = s.stats_snapshot()
    s.q("SELECT 2 AS b")
    assert before["issued"] == 0, "snapshot moved under the caller"
    s.close()


# --------------------------------------------------------- 6.2 stages in diagnose


def test_telemetry_reports_every_stage_of_the_detection_path(store):
    payload = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    t = payload.telemetry
    assert set(t.stage_ms) == DETECT_STAGES
    assert all(v >= 0 for v in t.stage_ms.values())


def test_total_is_at_least_the_sum_of_its_stages(store):
    """Structure, not a bound: total covers focal selection and payload construction
    too. The 0.9 slack absorbs perf_counter granularity, nothing more."""
    t = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store).telemetry
    assert t.total_ms >= sum(t.stage_ms.values()) * 0.9


def test_the_manual_window_path_reports_the_stages_it_actually_ran(store):
    """The sparse-history path skips detection and drill entirely. A hardcoded
    five-stage assertion would fail here -- and padding the dict with 0.0 for stages
    that never ran would read as 'instant' rather than 'skipped'."""
    payload = pipeline.diagnose(
        "mrr_renewals",
        pipeline.DEFAULT_AS_OF,
        store=store,
        cohort={"region": ["DACH"], "payment_rail": ["sepa"]},
        window=Window(start=date(2026, 8, 4), end=date(2026, 8, 17)),
    )
    assert payload is not None
    assert set(payload.telemetry.stage_ms) == MANUAL_STAGES


def test_query_counts_are_internally_consistent(store):
    """Absolute values are NOT asserted: the session-scoped store fixture is warm in
    an order-dependent way, so executed-vs-cached varies by test order."""
    t = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store).telemetry
    assert t.queries_executed >= 0 and t.queries_cached >= 0
    assert t.queries_executed + t.queries_cached > 0


def test_telemetry_is_per_diagnosis_not_since_boot(store):
    """Snapshot-and-subtract. A long-lived Store (which is what Streamlit has) must
    report this diagnosis, not every diagnosis it has ever served."""
    a = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store).telemetry
    b = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store).telemetry
    total_a = a.queries_executed + a.queries_cached
    total_b = b.queries_executed + b.queries_cached
    assert total_a == total_b, "counts accumulated instead of resetting per call"


# ------------------------------------------------------ 6.3 telemetry on the card


def test_the_card_carries_the_telemetry_the_payload_measured(store):
    card = pipeline.run("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    assert card.telemetry is not None
    assert set(card.telemetry.stage_ms) >= DETECT_STAGES


def test_narration_is_timed_as_its_own_stage(store):
    """Narration is a real step a user waits through. Leaving it out would make the
    panel's total quietly smaller than the wall clock they experienced."""
    card = pipeline.run("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    assert "narrate" in card.telemetry.stage_ms


def test_queries_on_card_matches_the_provenance_audit(store):
    """The provenance number, and it must equal what the audit actually finds --
    otherwise the panel claims an auditability it cannot deliver."""
    card = pipeline.run("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    assert card.telemetry.queries_on_card == len(pipeline.card_query_ids(card))
    assert card.telemetry.queries_on_card > 10


def test_the_provenance_count_is_smaller_than_the_work_done():
    """The correction that motivated this whole design: ~22 ids on the card against
    ~89 registered queries executed cold. Reporting the former as 'queries' in a
    runtime panel understates the work by roughly 4x. Both numbers are real; they
    answer different questions and must never be merged into one field.

    Opens its own store so the cache is genuinely cold -- the shared fixture is warm.
    """
    fresh = pipeline.get_store()
    card = pipeline.run("mrr_renewals", pipeline.DEFAULT_AS_OF, store=fresh)
    t = card.telemetry
    assert t.queries_on_card < t.queries_executed + t.queries_cached
    fresh.close()


def test_offline_path_makes_no_model_calls(store):
    """The claim the whole README rests on, asserted rather than stated."""
    card = pipeline.run("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    t = card.telemetry
    assert (t.llm_calls, t.llm_tokens, t.llm_cost_usd) == (0, 0, 0.0)
    assert card.generated_by == "template"


def test_every_persona_gets_the_same_zero(store):
    payload = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    for pid in ("analyst", "cfo", "oncall", "growth"):
        card = narrate.narrate(payload, persona=personas.get(pid))
        assert card.telemetry.llm_calls == 0


def test_the_abstention_card_is_also_accounted_for(store):
    """Abstaining is not free -- it costs the same drill and rank as answering. A
    telemetry panel that went blank on the honest branch would imply otherwise."""
    payload = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    card = narrate.narrate(payload, no_confident_cause=True)
    assert card.no_confident_cause is True
    assert card.telemetry is not None
    assert card.telemetry.queries_on_card == len(pipeline.card_query_ids(card))


def test_the_cards_total_covers_every_stage_it_lists(store):
    """The panel renders each stage's share of total. If narration is listed as a
    stage but excluded from the total, those shares sum past 100% -- a small number
    that makes a careful reader distrust the rest of the panel."""
    card = pipeline.run("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    t = card.telemetry
    assert t.total_ms >= sum(t.stage_ms.values()), (
        f"stages sum to {sum(t.stage_ms.values()):.1f} ms but total is {t.total_ms:.1f} ms"
    )
