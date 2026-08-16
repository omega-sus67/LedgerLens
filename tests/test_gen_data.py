from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import config
from ledgerlens.gen_data import live_slices


def test_slice_census():
    slices = live_slices()
    # card 6x3x3=54, sepa 3x3x3=27, invoice 6x1x3=18
    assert len(slices) == 99
    assert sum(1 for s in slices if s[2] == "sepa") == 27
    assert sum(1 for s in slices if s[2] == "invoice") == 18
    assert all(s[0] in config.SEPA_REGIONS for s in slices if s[2] == "sepa")
    assert all(s[1] == "Enterprise" for s in slices if s[2] == "invoice")


def test_target_cohort_is_three_slices(truth):
    # Exactly one slice per product. This is why MIN_SLICE_ROWS_PER_DAY must be a
    # strict `<` comparison in the drill-down: the answer sits AT the threshold.
    assert truth["n_target_slices"] == 3
    assert truth["n_live_slices"] == 99


def test_aggregate_delta_inside_required_band(truth):
    lo, hi = truth["expected_agg_delta_pct_range"]
    assert lo <= truth["observed_agg_delta_pct"] <= hi


def test_delta_decomposes_into_seasonality_plus_deploy(truth):
    # observed = (1 + deploy_only) * (1 + seasonal) - 1, which is what makes the
    # UI headline "Expected -1.2%, unexplained -7.0%" computable rather than prose.
    deploy = truth["deploy_only_delta_pct"] / 100
    seasonal = truth["seasonal_delta_pct"] / 100
    observed = truth["observed_agg_delta_pct"] / 100
    assert abs((1 + deploy) * (1 + seasonal) - 1 - observed) < 1e-6
    assert abs(truth["deploy_only_delta_pct"] - (-7.055)) < 0.05


def test_target_share_hits_solved_value(truth):
    assert abs(truth["target_share"] - config.TARGET_SHARE) < 1e-4


def test_impact_is_the_headline_number(truth):
    assert abs(truth["true_impact_abs"] - config.TARGET_IMPACT_ABS) < 1.0


def test_event_files_have_expected_breakdown(store):
    events = store.events()
    assert len(events) == 13
    assert Counter(e.event_type for e in events) == {
        "deploy": 9,
        "feature_flag": 2,
        "campaign": 1,
        "price_change": 1,
    }


def test_ticket_spike_is_half_prose(store):
    # Selected by error code, not by cohort: baseline tickets are scattered across
    # all regions and a few legitimately land in DACH/Enterprise during the window.
    total, coded = store.con.execute(
        "SELECT count(*), count(error_code) FROM ticket "
        "WHERE error_code = 'ERR_SEPA_504' OR error_code IS NULL"
    ).fetchone()
    assert total == config.INJECTED_TICKETS
    assert coded == config.INJECTED_TICKETS // 2  # the other half mention it only in prose


def test_fact_table_loaded(store):
    n = store.con.execute("SELECT count(*) FROM fact_metric").fetchone()[0]
    assert n == 99 * 549 * 2


def test_package_never_reads_ground_truth():
    """Spec 4.3: only tests/ may read ground_truth.json. The grep excludes
    gen_data.py, which legitimately WRITES it -- a bare grep fails on its own
    writer, which is pitfall #3 in the spec's own register."""
    pkg = Path(config.ROOT) / "ledgerlens"
    offenders = [
        p.relative_to(config.ROOT)
        for p in pkg.rglob("*.py")
        if p.name != "gen_data.py" and "ground_truth" in p.read_text()
    ]
    assert offenders == [], f"package modules must not read ground truth: {offenders}"


def test_tests_do_read_ground_truth():
    """The other half of the isolation proof: the fixture really does load it, so
    the assertion above is meaningful rather than vacuously true."""
    conftest = (Path(config.ROOT) / "tests" / "conftest.py").read_text()
    assert "ground_truth.json" in conftest


def test_generator_is_deterministic(tmp_path, truth):
    from ledgerlens.gen_data import generate

    again = generate(tmp_path)
    assert again == truth
    a = (tmp_path / "metrics.parquet").read_bytes()
    b = (config.DATA_DIR / "metrics.parquet").read_bytes()
    assert a == b
