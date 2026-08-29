"""Store-level aggregation semantics.

The interesting case is the ratio KPI: `fact_metric` is additive, so a rate has to be
assembled from two physical metrics at query time rather than stored directly.
"""

from __future__ import annotations

from datetime import date

from ledgerlens.models import Window


def test_ratio_series_is_a_weighted_rate_not_a_sum(store):
    """SUM(value) across 99 slices would give ~97; a rate must stay in [0, 1].
    And it must be WEIGHTED -- an unweighted mean of per-slice rates is not the
    overall rate, and we do not ship numbers we cannot defend."""
    s, qid = store.series("payment_success_rate", {}, date(2026, 7, 10), date(2026, 7, 20))
    assert not s.empty
    assert s.dropna().between(0.0, 1.0).all()
    assert qid  # still a registered, replayable query

    num, _ = store.series("payment_successes", {}, date(2026, 7, 10), date(2026, 7, 20))
    den, _ = store.series("payment_attempts", {}, date(2026, 7, 10), date(2026, 7, 20))
    expected = (num / den).dropna()
    assert (s.dropna() - expected).abs().max() < 1e-12


def test_ratio_cohort_rows_counts_the_denominator(store):
    """cohort_rows filters on metric_name. Without the source_metrics mapping it
    returns 0 for a ratio KPI, which drives C to 0.0 for every candidate and
    silently destroys the ranking on this KPI alone."""
    w = Window(start=date(2026, 8, 4), end=date(2026, 8, 17))
    n, _ = store.cohort_rows({"region": ["DACH"]}, w, "payment_success_rate")
    assert n > 0
