from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

import config
from ledgerlens import anomaly
from ledgerlens.models import Window

AS_OF = date(2026, 8, 17)


@pytest.fixture(scope="module")
def root(store):
    return anomaly.detect(store, "mrr_renewals", AS_OF)


@pytest.fixture(scope="module")
def nodes(store, root):
    return anomaly.drill(store, root)


def test_onset_is_exact(root, truth):
    assert root.onset == date.fromisoformat(truth["onset"])


def test_window_is_fourteen_days(root):
    assert root.window.start == root.onset
    assert root.window.days == config.WINDOW_LENGTH_DAYS


def test_root_delta_is_materially_negative(root):
    # Deliberately looser than the generator band asserted in test_gen_data: there
    # the counterfactual is known exactly, here `expected` is an ESTIMATE fitted on
    # the pre-window, so a point or so of fit error is expected and honest.
    assert -9.5 <= root.delta_pct <= -7.0


def test_focal_cohort_matches_ground_truth(store, nodes, truth):
    f = anomaly.focal(nodes)
    assert {k: sorted(v) for k, v in f.cohort.items()} == {
        k: sorted(v) for k, v in truth["true_cohort"].items()
    }
    assert f.depth == 3
    assert f.residual_z < -20


def test_focal_does_not_over_drill_into_product(nodes):
    # product survives the contribution floor at every level but never wins the
    # dimension choice; MAX_DRILL_DEPTH then makes a 4-dim cohort unreachable.
    f = anomaly.focal(nodes)
    assert "product" not in f.cohort


def test_focal_slice_sits_at_the_thin_slice_threshold(nodes):
    # 3 products = 3 rows/day, exactly MIN_SLICE_ROWS_PER_DAY. If the guard were
    # written `<=` instead of `<` the true cause would be filtered out entirely.
    f = anomaly.focal(nodes)
    assert f.rows_per_day == config.MIN_SLICE_ROWS_PER_DAY


def test_focal_shortfall_is_close_to_true_impact(nodes, truth):
    f = anomaly.focal(nodes)
    assert abs(f.delta_abs - truth["true_impact_abs"]) < 0.05 * abs(truth["true_impact_abs"])


def test_contributions_are_not_clamped(nodes):
    # A child above 1.0 with a sibling below 0 is real information (one slice worse
    # than the headline, another masking it), so the values are reported as computed.
    assert all(-5 < n.contribution < 5 for n in nodes)


def test_children_carry_parent_links(nodes):
    ids = {n.anomaly_id for n in nodes}
    for n in nodes:
        if n.depth == 0:
            assert n.parent_id is None
        else:
            assert n.parent_id in ids


def test_bh_labels_present_and_non_gating(nodes):
    # Every node on the focal path is ~1e-15, so BH survives trivially; it must not
    # be able to remove anything from the tree.
    assert all(n.bh_survived for n in nodes if n.depth > 0)


def test_no_flag_before_the_incident(store):
    """The August seasonal dip alone must not trigger. Data runs from 2025-03, so
    the scan genuinely sees August 2025 and has to decline to flag it."""
    assert anomaly.detect(store, "mrr_renewals", date(2026, 7, 31)) is None


def test_prior_august_is_below_threshold(store):
    """The seasonal dip is real but small: statistically visible, practically
    immaterial. This is exactly the 'meaningful change vs normal noise' split."""
    series, _ = store.series(
        "mrr_renewals", {}, date(2025, 8, 1) - timedelta(days=config.PRE_WINDOW_DAYS), date(2025, 8, 31)
    )
    ev = anomaly.evaluate(series, Window(start=date(2025, 8, 1), end=date(2025, 8, 31)))
    assert abs(ev.delta_pct) < config.MIN_ABS_DELTA_PCT


def test_seasonality_is_estimated_from_data(store):
    pct, query_id = anomaly.seasonal_estimate(store, "mrr_renewals", {})
    assert query_id.startswith("q_")
    assert abs(pct - 100 * (config.AUGUST_DIP - 1)) < 0.5


def test_mad_must_come_from_the_pre_window(store, nodes):
    """The bug spec 7.1 warns about, as one assertion.

    If median/MAD are computed over the anomaly window itself, every day in it is
    ~85% low, the residual median moves with them, and the z-score collapses toward
    zero -- the anomaly defines its own normal and detection silently dies.
    """
    f = anomaly.focal(nodes)
    series, _ = store.series(
        "mrr_renewals",
        f.cohort,
        f.window.start - timedelta(days=config.PRE_WINDOW_DAYS),
        f.window.end,
    )
    correct = anomaly.evaluate(series, f.window)
    assert correct.residual_z < -config.MAD_Z_THRESHOLD

    win = series[series.index >= str(f.window.start)].dropna()
    fit = anomaly.fit_pre_window(series[series.index < str(f.window.start)])
    coef, wf, _, _ = fit
    n_pre = len(series[series.index < str(f.window.start)].dropna())
    expected = anomaly.project(coef, wf, n_pre, win.index)
    resid = win.to_numpy(dtype=float) - expected
    med_in = float(np.median(resid))
    mad_in = float(np.median(np.abs(resid - med_in)))
    z_contaminated = float(
        np.mean(0.6745 * (resid - med_in) / max(mad_in, anomaly.EPS))
    )
    assert abs(z_contaminated) < config.MAD_Z_THRESHOLD
    assert abs(z_contaminated) < abs(correct.residual_z) / 10
