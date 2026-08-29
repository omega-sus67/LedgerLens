"""Personas and business levers.

A persona is a RENDERING concern and nothing else. It never reaches the store, the
ranker or the controls -- which is why the same NarrationPayload can be rendered four
ways and still produce a byte-identical card_query_ids() list. That property is the
pitch; `tests/test_narrate_personas.py` is where it is enforced.

`decision_rights` makes the brief's "decision rights" mechanical: a persona that does
not hold a lever is shown an ESCALATION, never an instruction. A CFO is not told to
roll back a release.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class Lever(BaseModel):
    """A thing the business can actually pull. Distinct from the action, which is the
    specific way you pull it this time."""

    model_config = ConfigDict(frozen=True)
    lever_id: str
    name: str
    owner_role: str


OWNER_LABEL: dict[str, str] = {
    "service_owner": "the team owning the service",
    "revops": "revenue operations",
    "growth": "growth marketing",
    "data_platform": "data platform",
}

LEVERS: dict[str, Lever] = {
    lever.lever_id: lever
    for lever in [
        Lever(
            lever_id="rollback_release",
            name="Roll back or hotfix a release",
            owner_role="service_owner",
        ),
        Lever(
            lever_id="disable_flag",
            name="Disable a feature flag",
            owner_role="service_owner",
        ),
        Lever(
            lever_id="restore_campaign_budget",
            name="Restore or re-target campaign budget",
            owner_role="growth",
        ),
        Lever(
            lever_id="revert_price",
            name="Revert or grandfather a price change",
            owner_role="revops",
        ),
        Lever(
            lever_id="hold_forecast",
            name="Hold the forecast, reclassify as at-risk",
            owner_role="revops",
        ),
        Lever(
            lever_id="connect_source",
            name="Connect a missing source system",
            owner_role="data_platform",
        ),
        Lever(
            lever_id="investigate_change",
            name="Investigate the change manually",
            owner_role="service_owner",
        ),
    ]
}

# Event type -> the lever that change is pulled with. Anything unmapped falls back to
# investigate_change: policy_change, external and vendor_incident are real values in
# config.SEGMENT_AGNOSTIC_EVENT_TYPES and must never crash the narrator.
_LEVER_BY_EVENT_TYPE: dict[str, str] = {
    "deploy": "rollback_release",
    "feature_flag": "disable_flag",
    "campaign": "restore_campaign_budget",
    "price_change": "revert_price",
}


def lever_for_event(event_type: str) -> Lever:
    return LEVERS[_LEVER_BY_EVENT_TYPE.get(event_type, "investigate_change")]


class Persona(BaseModel):
    """Who is reading the card. Controls prose, depth and decision rights -- never a
    number."""

    model_config = ConfigDict(frozen=True)

    persona_id: str
    label: str
    role: str  # keys contracts.AccessRule.role -- Task 4 joins on this
    channel: str
    depth: Literal["full", "summary", "operational"]
    show_event_ids: bool
    show_control_table: bool
    max_actions: int
    decision_rights: list[str]  # lever ids, or ["*"] for all


PERSONAS: dict[str, Persona] = {
    p.persona_id: p
    for p in [
        Persona(
            persona_id="analyst",
            label="Revenue Analyst",
            role="analyst",
            channel="workspace",
            depth="full",
            show_event_ids=True,
            show_control_table=True,
            max_actions=99,
            decision_rights=["*"],
        ),
        Persona(
            persona_id="cfo",
            label="CFO",
            role="finance",
            channel="email digest",
            depth="summary",
            show_event_ids=False,
            show_control_table=False,
            max_actions=2,  # the escalated P0 + hold_forecast, which the CFO owns
            decision_rights=["hold_forecast"],
        ),
        Persona(
            persona_id="oncall",
            label="Payments On-Call",
            role="payments_oncall",
            channel="pager",
            depth="operational",
            show_event_ids=True,
            show_control_table=True,
            max_actions=2,
            decision_rights=["rollback_release", "disable_flag"],
        ),
        Persona(
            persona_id="growth",
            label="Growth Marketing",
            role="growth",
            channel="workspace",
            depth="summary",
            show_event_ids=False,
            show_control_table=False,
            max_actions=2,
            decision_rights=["restore_campaign_budget"],
        ),
    ]
}

DEFAULT_PERSONA_ID = "analyst"


def get(persona_id: str) -> Persona:
    if persona_id not in PERSONAS:
        raise KeyError(f"unknown persona {persona_id!r}; known: {sorted(PERSONAS)}")
    return PERSONAS[persona_id]


def holds(persona: Persona, lever_id: str) -> bool:
    return "*" in persona.decision_rights or lever_id in persona.decision_rights
