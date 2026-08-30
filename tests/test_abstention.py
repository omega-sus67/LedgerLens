"""Abstention, on the path a demo can actually reach.

The `_no_cause_card` branch has always existed and has always been written well. Until
now there was no way to reach it without editing source, which means the single most
important claim this product makes -- "when it doesn't know, it says so" -- was the one
claim nobody could watch happen.

A source-drop switch makes it reachable: disconnect the deploy feed and the true cause
stops being a candidate at all, so nothing clears the score floor and the engine
refuses. Closes nothing new on the checklist; hardens MPE row 5, which is the row the
whole pitch rests on.
"""

from __future__ import annotations

import config
from ledgerlens import contracts, narrate, personas, pipeline

DROP_GITHUB = frozenset({"github"})


def test_dropping_the_deploy_source_forces_abstention(store):
    payload = pipeline.diagnose(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, drop_sources=DROP_GITHUB
    )
    assert payload is not None
    assert payload.no_confident_cause is True
    card = narrate.narrate(payload)
    assert card.no_confident_cause is True
    assert card.actions[0].lever == "connect_source"


def test_the_true_cause_is_not_merely_demoted_but_absent(store):
    """The switch simulates a source that was never connected, not one that scored
    badly. deploy_sepa_v214 must not appear anywhere on the card -- ranked, rejected,
    or in the evidence -- because an unconnected system produces no rows to reason
    about."""
    payload = pipeline.diagnose(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, drop_sources=DROP_GITHUB
    )
    seen = [h.event.event_id for h in payload.ranked + payload.rejected]
    assert "deploy_sepa_v214" not in seen
    assert all(h.event.source != "github" for h in payload.ranked + payload.rejected)


def test_the_decoy_is_still_rejected_not_promoted(store):
    """The risk the plan named. Dropping github removes the other deploys too, so the
    campaign decoy faces a thinner field -- but it must still die by its own control
    rather than winning by default. A decoy that gets promoted the moment competition
    is removed would mean the control was never doing the work."""
    payload = pipeline.diagnose(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, drop_sources=DROP_GITHUB
    )
    rejected_ids = [h.event.event_id for h in payload.rejected]
    assert "campaign_dach_cut" in rejected_ids
    assert "campaign_dach_cut" not in [h.event.event_id for h in payload.ranked]


def test_abstention_is_identical_for_every_persona(store):
    """Re-asserted on the REACHABLE path: a CFO must never be handed a confident
    answer the analyst was refused."""
    payload = pipeline.diagnose(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, drop_sources=DROP_GITHUB
    )
    for pid in ("analyst", "cfo", "oncall", "growth"):
        card = narrate.narrate(payload, persona=personas.get(pid))
        assert card.no_confident_cause is True, pid


def test_no_drop_is_byte_identical_to_today(store):
    """The default must not move. An empty drop set is not a special case."""
    a = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    b = pipeline.diagnose(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, drop_sources=frozenset()
    )
    assert [h.hypothesis_id for h in a.ranked] == [h.hypothesis_id for h in b.ranked]
    assert a.no_confident_cause is b.no_confident_cause is False


# ------------------------------------------- the card must not contradict the demo


def test_the_card_never_claims_a_dropped_source_is_connected(store):
    """The bug this task existed to find. `_no_cause_card` hardcoded its connectivity
    prose, so simulating a disconnected github printed 'Connected sources: deploys
    (github)...' -- the card contradicting the scenario, on stage, in the one branch
    whose entire purpose is honesty about what we do not have."""
    payload = pipeline.diagnose(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, drop_sources=DROP_GITHUB
    )
    card = narrate.narrate(payload)
    connected_half = card.summary.split("Not connected")[0]
    assert "github" not in connected_half, "card claims a dropped source is connected"
    assert "github" in card.summary, "card must still NAME what is missing"


def test_the_connected_list_is_read_off_the_contract_not_hardcoded(store):
    """Lineage is the contract's job. A prose list retyped into the narrator drifts
    the moment a connector is added, and drifts silently."""
    payload = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    card = narrate.narrate(payload, no_confident_cause=True)
    context = {
        s.source_system
        for s in contracts.get("mrr_renewals").lineage
        if s.kind == "context"
    }
    for source in context:
        assert source in card.summary, f"{source} is in the lineage but not on the card"


def test_the_action_names_the_source_to_reconnect(store):
    """The P1 must be actionable. 'Connect CRM/competitor pricing/macro indicators' is
    a wish; 'reconnect github' is a ticket somebody can close."""
    payload = pipeline.diagnose(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, drop_sources=DROP_GITHUB
    )
    action = narrate.narrate(payload).actions[0]
    assert action.lever == "connect_source"
    assert "github" in action.action


def test_with_nothing_dropped_the_action_falls_back_to_the_unconnected_systems(store):
    """No simulation running: there is no source to reconnect, so the honest ask is
    still the standing gap -- the systems we have never had a feed for."""
    payload = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    action = narrate.narrate(payload, no_confident_cause=True).actions[0]
    assert action.lever == "connect_source"
    assert "github" not in action.action
