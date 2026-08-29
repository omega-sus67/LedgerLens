"""The acceptance test. If this passes, the product works.

It asserts the two claims the whole design exists to support: the true cause ranks
first, and the plausible decoy is not merely outranked but explicitly rejected with
the control that killed it -- plus the provenance guarantee that makes both auditable.
"""

from __future__ import annotations

import time
from datetime import date

import pytest

import config
from ledgerlens import pipeline
from ledgerlens.models import Window

AS_OF = date(2026, 8, 17)


@pytest.fixture(scope="module")
def card(store):
    return pipeline.run("mrr_renewals", AS_OF, store=store)


def test_true_cause_ranks_first(card, truth):
    assert card.ranked[0].event.event_id == truth["true_cause_event_id"]
    assert card.ranked[0].total == pytest.approx(0.70, abs=0.01)


def test_decoy_is_rejected_not_merely_outranked(card, truth):
    """Being second is not good enough. A decoy that is still on the list is a decoy
    an analyst might act on."""
    rejected_ids = [h.event.event_id for h in card.rejected]
    ranked_ids = [h.event.event_id for h in card.ranked]
    for decoy in truth["must_not_rank_top"]:
        assert decoy in rejected_ids
        assert decoy not in ranked_ids


def test_us_pricing_decoy_never_appears_at_all(card):
    everything = [h.event.event_id for h in card.ranked + card.rejected]
    assert "pricing_us_q3" not in everything


def test_focal_cohort_is_the_true_cohort(card, truth):
    assert {k: sorted(v) for k, v in card.focal.cohort.items()} == {
        k: sorted(v) for k, v in truth["true_cohort"].items()
    }


def test_card_is_deterministic_without_an_api_key(card):
    """Spec 0.2: with ANTHROPIC_API_KEY unset the pipeline must still produce a
    complete, correct card. Both investigator lanes stay empty and nothing an LLM
    could emit is on the ranking path."""
    assert card.generated_by == "template"
    assert card.proposed_tests == []
    assert card.unverified == []


def test_narration_never_overclaims_causation(card):
    assert "most consistent with" in card.headline
    assert "caused by" not in card.headline.lower()
    assert "does not prove causation" in card.summary


def test_headline_numbers_appear_in_the_underlying_objects(card):
    """The narrator copies figures, it does not compute them."""
    assert f"{abs(card.focal.delta_pct):.0f}%" in card.headline
    assert card.ranked[0].event.event_id in card.headline


def test_every_query_id_is_registered_and_reproducible(store, card):
    """The anti-hallucination mechanism, asserted: walk the finished card, collect
    every query id, and prove each one both exists and still returns what it claimed."""
    ids = pipeline.card_query_ids(card)
    assert len(ids) > 10
    for query_id in ids:
        row = store.query_row(query_id)
        assert row is not None, f"{query_id} missing from query_log"
        sql, stored, fresh = store.replay(query_id)
        assert stored == fresh, f"{query_id} no longer reproduces its logged preview"


def test_evidence_steps_all_carry_provenance(card):
    assert card.causal_chain
    for step in card.causal_chain:
        assert step.query_id.startswith("q_")
        assert step.observed


def test_actions_cite_a_number_and_a_query(card):
    assert card.actions
    for action in card.actions:
        assert "q_" in action.basis


def test_second_finding_is_surfaced(card):
    """The campaign did not cause the renewals drop, but it did cut new-logo
    bookings ~31%. Reporting that is the difference between clearing a suspect and
    understanding what actually happened."""
    p2 = [a for a in card.actions if a.priority == "P2"]
    assert p2
    assert "new_logo_bookings" in p2[0].basis


def test_manual_slice_targeting_bypasses_detection(store):
    """Detection is advisory, not gating: pointing the pipeline at a slice directly
    must produce the same diagnosis without any detector involvement."""
    card = pipeline.run(
        "mrr_renewals",
        AS_OF,
        store=store,
        cohort=config.TARGET_COHORT,
        window=Window(start=date(2026, 8, 3), end=date(2026, 8, 16)),
    )
    assert card.ranked[0].event.event_id == "deploy_sepa_v214"
    assert "campaign_dach_cut" in [h.event.event_id for h in card.rejected]


def test_no_anomaly_before_the_incident(store):
    card = pipeline.run("mrr_renewals", date(2026, 7, 31), store=store)
    assert card.ranked == []
    assert "No anomaly" in card.headline


def test_runs_within_the_latency_budget(store):
    fresh = pipeline.get_store()
    start = time.perf_counter()
    pipeline.run("mrr_renewals", AS_OF, store=fresh)
    elapsed = time.perf_counter() - start
    fresh.close()
    assert elapsed < 5.0, f"pipeline took {elapsed:.1f}s"


def test_diagnose_and_run_agree_on_every_query_id(store):
    """run() must be exactly narrate(diagnose()). If these ever diverge, the
    'same evidence, different narrative' claim is dead."""
    from ledgerlens import narrate

    payload = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    assert payload is not None
    from_payload = narrate.narrate(payload)
    from_run = pipeline.run("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)

    assert pipeline.card_query_ids(from_payload) == pipeline.card_query_ids(from_run)
    assert from_payload.summary == from_run.summary
    assert from_payload.headline == from_run.headline


def test_diagnose_returns_none_when_there_is_no_anomaly(store):
    from datetime import date

    assert pipeline.diagnose("mrr_renewals", date(2026, 7, 31), store=store) is None


def test_payload_carries_the_abstention_flag(store):
    payload = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    assert payload.no_confident_cause is False
