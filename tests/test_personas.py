"""Persona + lever registries. Pure data, so these are fast and exhaustive."""

from __future__ import annotations

import pytest

import config
from ledgerlens import personas


def test_four_personas_exist_and_analyst_is_default():
    assert set(personas.PERSONAS) == {"analyst", "cfo", "oncall", "growth"}
    assert personas.DEFAULT_PERSONA_ID == "analyst"


def test_analyst_holds_every_lever_via_wildcard():
    """The analyst routes work rather than owning levers, so every action renders
    as written. This is what keeps today's card byte-identical."""
    analyst = personas.get("analyst")
    assert analyst.decision_rights == ["*"]
    for lever_id in personas.LEVERS:
        assert personas.holds(analyst, lever_id)


def test_cfo_cannot_roll_back_a_release():
    """The decision-rights claim, at its sharpest: a CFO is never told to deploy."""
    cfo = personas.get("cfo")
    assert not personas.holds(cfo, "rollback_release")
    assert personas.holds(cfo, "hold_forecast")


def test_oncall_holds_the_operational_levers_only():
    oncall = personas.get("oncall")
    assert personas.holds(oncall, "rollback_release")
    assert personas.holds(oncall, "disable_flag")
    assert not personas.holds(oncall, "hold_forecast")


def test_growth_role_matches_the_contract_access_rule():
    """contracts.py declares AccessRule(role="growth"). Task 4 joins on this string,
    so a typo here is a silent entitlement bypass later."""
    from ledgerlens import contracts

    roles = {r.role for c in contracts.CONTRACTS.values() for r in c.access}
    assert personas.get("growth").role in roles


def test_every_event_type_maps_to_a_lever():
    """No event type may crash the narrator. SEGMENT_AGNOSTIC_EVENT_TYPES contains
    policy_change / external / vendor_incident, none of which have a named lever."""
    known = {"deploy", "feature_flag", "campaign", "price_change"}
    for event_type in known | config.SEGMENT_AGNOSTIC_EVENT_TYPES:
        lever = personas.lever_for_event(event_type)
        assert lever.lever_id in personas.LEVERS


def test_unknown_event_type_falls_back_rather_than_raising():
    assert personas.lever_for_event("something_new").lever_id == "investigate_change"


def test_every_lever_owner_role_has_a_human_label():
    for lever in personas.LEVERS.values():
        assert lever.owner_role in personas.OWNER_LABEL


def test_get_rejects_an_unknown_persona():
    with pytest.raises(KeyError):
        personas.get("ceo")
