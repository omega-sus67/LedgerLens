"""Two audiences, identical evidence.

'Different narratives, same query_ids' is the sentence we say to judges. This file is
that sentence, machine-checked. If it ever goes red, the claim is retracted -- do not
weaken the assertion to make it pass.
"""

from __future__ import annotations

import dataclasses

import pytest

from ledgerlens import narrate, personas, pipeline

PERSONA_IDS = ["analyst", "cfo", "oncall", "growth"]


@pytest.fixture(scope="module")
def payload(store):
    p = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    assert p is not None
    return p


@pytest.fixture(scope="module")
def cards(payload):
    return {pid: narrate.narrate(payload, persona=personas.get(pid)) for pid in PERSONA_IDS}


def test_personas_differ_in_prose_but_share_every_query_id(cards):
    """THE assertion. Four different summaries; one identical evidence set."""
    summaries = {c.summary for c in cards.values()}
    assert len(summaries) == len(PERSONA_IDS), "two personas produced identical prose"

    id_sets = [pipeline.card_query_ids(c) for c in cards.values()]
    assert all(ids == id_sets[0] for ids in id_sets), "personas diverged on evidence"
    assert len(id_sets[0]) > 10, "a card with almost no query ids proves nothing"


def test_ranked_and_rejected_are_byte_identical_across_personas(cards):
    """Prose may differ. The ranking may not."""
    ref = cards["analyst"]
    for pid, card in cards.items():
        assert [h.hypothesis_id for h in card.ranked] == [h.hypothesis_id for h in ref.ranked], pid
        assert [h.total for h in card.ranked] == [h.total for h in ref.ranked], pid
        assert [h.hypothesis_id for h in card.rejected] == [
            h.hypothesis_id for h in ref.rejected
        ], pid


def test_default_persona_reproduces_todays_card(payload):
    """The regression guard on the whole refactor: no persona argument must render
    exactly what the analyst persona renders."""
    default = narrate.narrate(payload)
    analyst = narrate.narrate(payload, persona=personas.get("analyst"))
    assert default.summary == analyst.summary
    assert default.headline == analyst.headline
    assert [a.action for a in default.actions] == [a.action for a in analyst.actions]


def test_cfo_prose_never_leaks_an_event_id(cards):
    """'No SQL jargon, no event ids in prose' -- the CFO template's whole job. The
    action text counts: an escalation that names a sha is still a card with a sha."""
    cfo = cards["cfo"]
    text = f"{cfo.headline} {cfo.summary} " + " ".join(a.action for a in cfo.actions)
    assert "deploy_sepa_v214" not in text
    assert "query_id" not in text
    assert "Jaccard" not in text


def test_cfo_headline_leads_with_money(cards):
    assert "$" in cards["cfo"].headline


def test_oncall_headline_leads_with_the_event_id(cards):
    assert cards["oncall"].headline.startswith("deploy_sepa_v214")


def test_cfo_sees_fewer_actions_than_the_analyst(cards):
    """Persona.max_actions -- 'insight depth personalization' made mechanical."""
    assert len(cards["cfo"].actions) == 2
    assert len(cards["analyst"].actions) > len(cards["cfo"].actions)


def test_cfo_still_gets_the_lever_it_actually_owns(cards):
    """Truncation must not strip the one action a CFO can act on alone."""
    levers = [a.lever for a in cards["cfo"].actions]
    assert "hold_forecast" in levers


def test_cfo_is_never_told_to_roll_back_a_release(cards):
    """DECISION RIGHTS. A CFO does not hold rollback_release, so any action on that
    lever must render as an escalation, not an instruction."""
    cfo_actions = " ".join(a.action for a in cards["cfo"].actions)
    assert "Roll back" not in cfo_actions


def test_oncall_is_told_to_roll_back_directly(cards):
    """The mirror image: on-call DOES hold the lever, so no escalation wrapper."""
    p0 = next(a for a in cards["oncall"].actions if a.priority == "P0")
    assert p0.lever == "rollback_release"
    assert not p0.action.startswith("Escalate")


def test_escalation_names_the_owner(cards):
    """An escalation a reader cannot route is useless."""
    seen = False
    for a in cards["growth"].actions:
        if a.action.startswith("Escalate"):
            assert a.owner in a.action
            seen = True
    assert seen, "growth holds only restore_campaign_budget, so it must see an escalation"


def test_every_persona_abstains_together(payload):
    """Abstention is evidence-driven, so it cannot vary by audience. A CFO must not
    be given a confident answer the analyst was refused."""
    abstained = dataclasses.replace(payload, no_confident_cause=True)
    for pid in PERSONA_IDS:
        card = narrate.narrate(abstained, persona=personas.get(pid))
        assert card.no_confident_cause is True
