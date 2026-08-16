from __future__ import annotations

from datetime import date

import pytest

import config
from ledgerlens import anomaly, controls, hypothesis
from ledgerlens.ledger import symptoms as symptoms_mod
from ledgerlens.models import ControlResult, canonical_cohort_key

AS_OF = date(2026, 8, 17)


@pytest.fixture(scope="module")
def focal(store):
    root = anomaly.detect(store, "mrr_renewals", AS_OF)
    return anomaly.focal(anomaly.drill(store, root))


@pytest.fixture(scope="module")
def ranked(store, focal):
    return hypothesis.rank(store, focal, symptoms_mod.cluster(store, focal.window))


def _by_id(ranked, event_id):
    return next(h for h in ranked if h.event.event_id == event_id)


# ------------------------------------------------------------------ the decoy


def test_marketing_decoy_is_rejected(ranked, truth):
    campaign = _by_id(ranked, truth["must_not_rank_top"][0])
    assert campaign.rejection_reason is not None
    assert campaign.scores.N == 0.0


def test_rejection_names_the_control_that_killed_it(ranked):
    """The 15 seconds of the demo that a judge remembers: not just a low score, but
    a specific prediction that a specific cohort would move, and it didn't."""
    reason = _by_id(ranked, "campaign_dach_cut").rejection_reason
    assert "Mid" in reason and "SMB" in reason
    assert "should also drop" in reason


def test_segment_sibling_control_is_the_decisive_one(ranked):
    campaign = _by_id(ranked, "campaign_dach_cut")
    decisive = [c for c in campaign.controls if c.decisive]
    assert len(decisive) == 1
    assert decisive[0].rule == "R2 segment-siblings"
    assert decisive[0].prediction == "should_also_drop"
    assert decisive[0].observed_delta_pct > config.DECISIVE_FLAT_PCT


def test_campaign_did_cause_something_real_just_not_this(ranked):
    """The honest second finding: the budget cut really did cut new-logo bookings by
    ~30%. It is the wrong metric for this anomaly, not a harmless event."""
    campaign = _by_id(ranked, "campaign_dach_cut")
    objective = next(c for c in campaign.controls if c.rule == "R4 objective-mismatch")
    assert objective.metric == "new_logo_bookings"
    assert objective.passed
    assert objective.observed_delta_pct < -25


def test_decoy_ranks_last_and_below_the_score_floor(ranked):
    assert ranked[-1].event.event_id == "campaign_dach_cut"
    assert ranked[-1].total < config.SCORE_FLOOR


# ------------------------------------------------------------------ true cause


def test_true_cause_passes_at_least_three_controls(ranked):
    deploy = _by_id(ranked, "deploy_sepa_v214")
    assert sum(c.passed for c in deploy.controls) >= 3
    assert deploy.rejection_reason is None
    assert deploy.scores.N == 1.0


def test_true_cause_controls_are_four_distinct_checks(ranked):
    deploy = _by_id(ranked, "deploy_sepa_v214")
    rules = sorted(c.rule for c in deploy.controls)
    assert rules == [
        "R1 payment_rail-complement",
        "R1 region-complement",
        "R3 geo-complement",
        "R5 temporal-placebo",
    ]


def test_segment_sibling_control_is_not_applied_to_deploys(ranked):
    """Gating rule 2 on mechanism class is what stops it rejecting the TRUE cause:
    the deploy also leaves `segment` unconstrained, so an ungated rule would build
    the identical DACH x Mid|SMB control, find it flat, and throw out the answer."""
    deploy = _by_id(ranked, "deploy_sepa_v214")
    assert not any(c.rule == "R2 segment-siblings" for c in deploy.controls)
    assert "deploy" not in config.SEGMENT_AGNOSTIC_EVENT_TYPES


def test_card_rail_stayed_flat_while_sepa_collapsed(ranked):
    deploy = _by_id(ranked, "deploy_sepa_v214")
    rail = next(c for c in deploy.controls if c.rule == "R1 payment_rail-complement")
    assert rail.prediction == "should_be_flat"
    assert abs(rail.observed_delta_pct) < config.CONTROL_PASS_BAND_PCT
    assert rail.passed


# ------------------------------------------------------------------ mechanics


def test_controls_are_deduplicated(ranked):
    for h in ranked:
        keys = [
            (c.metric, canonical_cohort_key(c.cohort), c.prediction) for c in h.controls
        ]
        assert len(keys) == len(set(keys))


def test_every_control_is_reproducible(store, ranked):
    for h in ranked:
        for c in h.controls:
            sql, stored, fresh = store.replay(c.query_id)
            assert stored == fresh


@pytest.mark.parametrize(
    "prediction,observed,expected",
    [
        ("should_be_flat", -8.0, True),  # supposedly unaffected cohort fell with it
        ("should_be_flat", -1.2, False),  # ordinary seasonality
        ("should_also_drop", -1.2, True),  # predicted to fall, plainly did not
        ("should_also_drop", -30.0, False),  # fell as predicted
        ("should_also_drop", -3.5, False),  # ambiguous: lowers N, does not reject
    ],
)
def test_decisive_failure_covers_both_directions(prediction, observed, expected):
    cr = ControlResult(
        name="t",
        cohort={"region": ["DACH"]},
        prediction=prediction,
        observed_delta_pct=observed,
        passed=False,
        query_id="q_x",
    )
    assert controls.decisive_failure(cr) is expected


def test_decisive_failure_zeroes_n_regardless_of_passes():
    """A mechanism that predicted something which plainly did not happen cannot be
    rescued by other checks agreeing."""
    passing = [
        ControlResult(
            name=f"ok{i}",
            cohort={"region": ["UK"]},
            prediction="should_be_flat",
            observed_delta_pct=-1.0,
            passed=True,
            query_id=f"q_{i}",
        )
        for i in range(4)
    ]
    killer = ControlResult(
        name="killer",
        cohort={"region": ["DACH"]},
        prediction="should_also_drop",
        observed_delta_pct=-1.2,
        passed=False,
        decisive=True,
        query_id="q_k",
    )
    n, reason = controls.score_n(passing + [killer])
    assert n == 0.0
    assert reason is not None
