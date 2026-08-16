from __future__ import annotations

import math
from datetime import date

import pytest

import config
from ledgerlens import anomaly, hypothesis
from ledgerlens.ledger import symptoms as symptoms_mod

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


def test_us_pricing_never_becomes_a_candidate(store, focal):
    """region US intersected with region DACH is the empty set, so the pricing decoy
    is eliminated by set algebra before any scoring happens."""
    ids = [e.event_id for e in hypothesis.candidates(store, focal)]
    assert "pricing_us_q3" not in ids


def test_candidate_set_is_the_expected_five(store, focal):
    ids = sorted(e.event_id for e in hypothesis.candidates(store, focal))
    assert ids == [
        "campaign_dach_cut",
        "deploy_billing_ui_v9",
        "deploy_dunning_v3",
        "deploy_sepa_v214",
        "flag_sepa_retry_beta",
    ]


def test_events_outside_lookback_are_excluded(store, focal):
    ids = [e.event_id for e in hypothesis.candidates(store, focal)]
    assert "deploy_search_reindex" not in ids  # merged 2026-07-05, beyond LOOKBACK_DAYS


def test_temporal_is_one_at_onset_and_decays(ranked):
    assert _by_id(ranked, "deploy_sepa_v214").scores.T == 1.0
    assert _by_id(ranked, "campaign_dach_cut").scores.T == pytest.approx(math.exp(-1 / 3), abs=1e-4)
    # enabled three days AFTER the drop began -- it cannot be the cause
    assert _by_id(ranked, "flag_sepa_retry_beta").scores.T == 0.0


def test_cohort_match_beats_the_decoy_on_row_geometry(ranked):
    """The component that kills the marketing decoy.

    The deploy's radius is DACH x SEPA = 9 slices against a 3-slice anomaly -> 1/3.
    The campaign's is all of DACH = 21 slices -> 1/7. Both contain the anomaly
    entirely, so only counting the ROWS each selects separates them.
    """
    c_deploy = _by_id(ranked, "deploy_sepa_v214").scores.C
    c_campaign = _by_id(ranked, "campaign_dach_cut").scores.C
    assert c_deploy == pytest.approx(1 / 3, abs=1e-6)
    assert 0.10 < c_campaign < 0.17
    assert c_deploy > 2 * c_campaign


def test_dose_response_is_honestly_uninformative(ranked):
    """Both blast radii fully contain the focal cohort, so every sub-slice has
    exposure 1.0 and a rank correlation is undefined. 0.5 is the correct answer;
    manufacturing a number here would be exactly the failure mode we exist to avoid."""
    assert all(h.scores.D == 0.5 for h in ranked)


def test_prior_starts_flat(ranked):
    assert all(h.scores.P == 0.5 for h in ranked)


def test_true_cause_ranks_first_by_a_clear_margin(ranked, truth):
    assert ranked[0].event.event_id == truth["true_cause_event_id"]
    assert ranked[0].total == pytest.approx(0.70, abs=0.01)
    # gap far exceeds AMBIGUITY_EPSILON, so this incident is not a close call
    assert ranked[0].total - ranked[1].total > config.AMBIGUITY_EPSILON


def test_symptoms_attach_but_do_not_score(ranked):
    """Ticket evidence corroborates in the narrative; it is deliberately excluded
    from the rubric so it cannot double-count the signal C already measures."""
    top = _by_id(ranked, "deploy_sepa_v214")
    assert [c.key for c in top.symptoms] == ["ERR_SEPA_504"]
    recomputed = top.scores.total(config.SCORE_WEIGHTS)
    assert top.total == pytest.approx(recomputed, abs=1e-6)


def test_every_hypothesis_carries_resolvable_provenance(store, ranked):
    for h in ranked:
        assert h.query_ids
        for qid in h.query_ids:
            assert store.query_row(qid) is not None
