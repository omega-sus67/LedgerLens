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
