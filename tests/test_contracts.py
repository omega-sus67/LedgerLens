"""The KPI semantic contract, and the invariants the engine already rests on.

`contracts.py` is not documentation -- `anomaly.py` reads its thresholds and `app.py`
renders its lineage. That makes drift between contract and engine a live risk, so most
of what follows is drift detection rather than unit testing.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

import config
from ledgerlens import contracts
from ledgerlens.contracts import AccessRule, KpiContract, LineageStep, Thresholds

AS_OF = date(2026, 8, 17)


# ------------------------------------------------------------------- coverage


def test_every_metric_is_governed():
    """An ungoverned KPI would render an empty Contract box in the UI. Both
    directions, because a contract for a metric that no longer exists is drift too."""
    assert set(contracts.CONTRACTS) == set(config.METRICS)


def test_contract_key_matches_its_own_name():
    for key, contract in contracts.CONTRACTS.items():
        assert contract.name == key


# ----------------------------------------------------------------- thresholds


def test_threshold_defaults_are_exactly_the_global_constants():
    """THE load-bearing invariant. Wiring contracts into scan_for_onset()/drill() was
    only a behaviour-preserving refactor because an unset field falls back to the
    identical global constant. Nothing else in the suite guards it; if someone
    "tidies" a default here, detection changes silently on every metric at once.

    Asserted field by field so a failure names the constant that drifted."""
    th = Thresholds()
    assert th.mad_z == config.MAD_Z_THRESHOLD
    assert th.min_consecutive == config.MIN_CONSECUTIVE_PERIODS
    assert th.min_abs_delta_pct == config.MIN_ABS_DELTA_PCT
    assert th.warmup_days == config.DETECT_WARMUP_DAYS
    assert th.direction == config.DIRECTION


def test_mrr_thresholds_are_the_tuned_acceptance_values():
    """test_pipeline.py's acceptance test asserts the exact incident and the exact
    rejected decoy. Both are tuned to these four numbers -- changing one here is a
    deliberate act that should have to edit this line first."""
    th = contracts.thresholds("mrr_renewals")
    assert (th.mad_z, th.min_consecutive, th.min_abs_delta_pct, th.warmup_days) == (
        3.5,
        2,
        3.0,
        120,
    )


def test_every_contract_currently_uses_the_global_defaults():
    """True today, and worth knowing the moment it stops being true: Task 3's sparse
    KPI is supposed to diverge, and this test failing is how we confirm it did."""
    for contract in contracts.CONTRACTS.values():
        assert contract.thresholds == Thresholds()


# ----------------------------------------------------------------- validators


def _minimal(**overrides) -> dict:
    base = dict(
        name="x",
        definition="d",
        unit="USD/day",
        owner="o",
        calculation_sql="SELECT 1",
        grain_dims=["region"],
        drivers=[],
        related_event_types=["deploy"],
        lineage=[],
    )
    base.update(overrides)
    return base


def test_unknown_grain_dim_fails_at_construction():
    """Pydantic validators are the CI mechanism: a typo fails at import, in CI, not
    at demo time. That is the entire argument for Python over a YAML registry."""
    with pytest.raises(ValidationError, match="unknown dimensions"):
        KpiContract(**_minimal(grain_dims=["region", "regoin"]))


def test_unknown_hidden_dim_fails_at_construction():
    rule = AccessRule(policy_id="p.1", role="growth", hidden_dims=["payment_rale"], reason="r")
    with pytest.raises(ValidationError, match="unknown dimensions"):
        KpiContract(**_minimal(access=[rule]))


def test_unknown_event_type_fails_at_construction():
    with pytest.raises(ValidationError, match="unknown event types"):
        KpiContract(**_minimal(related_event_types=["deploy", "redeploy"]))

    with pytest.raises(ValidationError, match="unknown event types"):
        KpiContract(**_minimal(anticipated_event_types=["act_of_god"]))


def test_contracts_are_frozen():
    """Immutable by construction: nothing downstream may edit a threshold in place
    and leave the UI showing a policy that is not the one the engine applied."""
    with pytest.raises(ValidationError):
        contracts.get("mrr_renewals").thresholds.mad_z = 1.0


# ---------------------------------------------------------------- entitlement


def test_growth_cannot_drill_into_payment_rail():
    """The seed of Task 4. Policy fin.rail_detail hides the rail split from growth,
    and this is the list pipeline.run() will hand to anomaly.drill()."""
    dims = contracts.get("mrr_renewals").visible_drill_dims("growth")
    assert "payment_rail" not in dims
    assert dims == ["region", "segment", "product"]


def test_visible_dims_preserve_drill_order():
    """Order matters downstream: drill() picks a winning dimension per level, so a
    reordered list would silently change which cohort becomes focal."""
    dims = contracts.get("mrr_renewals").visible_drill_dims("growth")
    assert dims == [d for d in config.DRILL_DIMS if d != "payment_rail"]


def test_unknown_role_is_unrestricted():
    """Fail-OPEN, deliberately. The sensitive surface is a named subset of dimensions,
    not the metric; fail-closed would blank the page for every unnamed role."""
    assert contracts.get("mrr_renewals").visible_drill_dims("nobody") == config.DRILL_DIMS
    assert contracts.get("mrr_renewals").hidden_dims_for("nobody") == []


def test_policy_carries_an_id_and_a_reason():
    """Redaction has to be explicable. A hidden dimension with no policy id is an
    unexplained blank on the card."""
    for contract in contracts.CONTRACTS.values():
        for rule in contract.access:
            assert rule.policy_id and rule.reason


# --------------------------------------------------------------- lookup split


def test_get_refuses_an_ungoverned_kpi():
    with pytest.raises(KeyError, match="no contract registered"):
        contracts.get("nope")


def test_thresholds_degrades_to_defaults():
    """Deliberately asymmetric with get(): the UI must refuse to present a KPI nobody
    defined, but detection must not crash because metadata is missing."""
    assert contracts.thresholds("nope") == Thresholds()


# -------------------------------------------------------------- ledger drift


def test_related_event_types_are_present_in_the_ledger(store):
    """Guards the contract against gen_data.py. If a connector stops emitting a type
    the contract claims to watch, that is a silent blind spot -- catch it here."""
    present = {e.event_type for e in store.events()}
    for contract in contracts.CONTRACTS.values():
        assert set(contract.related_event_types) <= present


def test_anticipated_event_types_are_genuinely_absent(store):
    """The other direction, and the one that keeps the claim honest: anything we say
    we cannot see must actually be unseeable. A type that starts arriving belongs in
    `related`, and leaving it in `anticipated` would understate the system."""
    present = {e.event_type for e in store.events()}
    for contract in contracts.CONTRACTS.values():
        assert not (set(contract.anticipated_event_types) & present)


def test_lineage_sources_match_the_change_event_feed(store):
    """source_system is joined against change_event.source in the freshness query. A
    rename in connectors.py would otherwise show up as a permanently stale source."""
    sources = {e.source for e in store.events()}
    for contract in contracts.CONTRACTS.values():
        for step in contract.lineage:
            if step.kind == "context":
                assert step.source_system in sources


def test_every_lineage_kind_has_a_freshness_query():
    assert {s.kind for c in contracts.CONTRACTS.values() for s in c.lineage} <= set(
        contracts._FRESHNESS_SQL
    )


# ----------------------------------------------------------------- freshness


@pytest.fixture(scope="module")
def fresh(store):
    return contracts.freshness(store, "mrr_renewals", AS_OF)


def test_freshness_covers_every_lineage_step(fresh):
    assert len(fresh) == len(contracts.get("mrr_renewals").lineage)


def test_freshness_is_never_negative(fresh):
    """The regression test for the trap in this feature. The generator writes through
    GEN_END = 2026-08-31, two weeks PAST the replay's as-of date, so an unbounded
    max(date) reports the future and prints "-14 days stale" on stage."""
    assert all(f.lag_days >= 0 for f in fresh)
    assert all(f.last_seen <= AS_OF for f in fresh)


def test_metric_feed_is_fresher_than_the_planning_feed(fresh):
    """The point of showing cadence beside freshness: these sources are genuinely
    heterogeneous. A daily batch is current; a weekly planning export is two weeks
    behind, and that is a caveat on the CAUSE, not on the number."""
    by_source = {f.source_system: f for f in fresh}
    assert by_source["billing_db"].lag_days == 0
    assert by_source["calendar"].lag_days > by_source["billing_db"].lag_days


def test_freshness_numbers_are_replayable(store, fresh):
    """Every number a user reads carries the query that produced it. Freshness is not
    exempt -- this is why it routes through store.q() and not store.max_date()."""
    for f in fresh:
        assert store.query_row(f.query_id) is not None
        sql, stored, recomputed = store.replay(f.query_id)
        assert stored == recomputed


def test_declared_cadence_comes_from_the_contract(fresh):
    declared = {s.source_system: s.refresh_cadence for s in contracts.get("mrr_renewals").lineage}
    for f in fresh:
        assert f.declared_cadence == declared[f.source_system]


# ------------------------------------------------------- calculation_sql drift


@pytest.mark.parametrize("metric", config.METRICS)
def test_calculation_sql_reproduces_the_engine_series(store, metric):
    """The strongest anti-drift guard available: the SQL the UI shows a judge is
    executed and compared against what Store.series() actually feeds the detector.

    The two strings differ -- series() renders cohort_predicate({}) as an explicit
    'AND TRUE' that the contract elides -- so the RESULT is compared, not the text."""
    start, end = date(2026, 7, 1), AS_OF
    df, _ = store.q(
        contracts.get(metric).calculation_sql,
        {"start": start, "end": end},
        label=f"contract calculation_sql: {metric}",
    )
    series, _ = store.series(metric, {}, start, end)

    assert not df.empty
    assert len(df) == len(series)
    assert df["value"].to_numpy() == pytest.approx(series.to_numpy())
