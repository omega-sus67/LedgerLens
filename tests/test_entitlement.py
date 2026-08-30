"""Role-based entitlement: redaction WITH provenance.

The point is not that growth sees less. It is that growth is TOLD it sees less, by
which policy, and why -- a refusal that names itself is governance; a silently shorter
answer is a bug.

Closes Minimum Prototype Expectation row 7. Full rationale in
docs/roles_decisions.md; the plan this file was written against is
docs/taskflow/roles_tasks.md.
"""

from __future__ import annotations

import config
from ledgerlens import contracts, narrate, personas, pipeline
from ledgerlens.models import DiagnosisCard, Redaction


def test_redaction_carries_dim_policy_and_reason():
    r = Redaction(dim="payment_rail", policy_id="fin.rail_detail", reason="finance-restricted")
    assert (r.dim, r.policy_id) == ("payment_rail", "fin.rail_detail")


def test_cards_default_to_no_redactions():
    """Every existing construction site stays valid: the field is defaulted."""
    card = DiagnosisCard.no_anomaly("mrr_renewals", pipeline.DEFAULT_AS_OF)
    assert card.redactions == []


# ------------------------------------------------------- 4.2 enforcement at drill


def test_growth_never_sees_a_payment_rail_cut(store):
    payload = pipeline.diagnose(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="growth"
    )
    assert payload is not None
    assert all("payment_rail" not in n.cohort for n in payload.nodes)


def test_analyst_still_sees_every_cut(store):
    payload = pipeline.diagnose(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="analyst"
    )
    assert any("payment_rail" in n.cohort for n in payload.nodes)


def test_no_role_is_byte_identical_to_the_analyst_role(store):
    """Fail-open, proven: an unrestricted role must not perturb today's card."""
    none_role = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    analyst = pipeline.diagnose(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="analyst"
    )
    assert [n.anomaly_id for n in none_role.nodes] == [n.anomaly_id for n in analyst.nodes]
    assert none_role.focal.anomaly_id == analyst.focal.anomaly_id


def test_diagnose_reports_what_it_withheld(store):
    payload = pipeline.diagnose(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="growth"
    )
    assert [r.dim for r in payload.redactions] == ["payment_rail"]
    assert payload.redactions[0].policy_id == "fin.rail_detail"
    # The reason is the contract's declared string, never prose invented here.
    rule = contracts.get("mrr_renewals").access[0]
    assert payload.redactions[0].reason == rule.reason


def test_an_unrestricted_role_redacts_nothing(store):
    payload = pipeline.diagnose(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="analyst"
    )
    assert payload.redactions == []


# ------------------------------------------------------- 4.3 stating the refusal


def test_redaction_names_its_policy_on_the_card(store):
    card = pipeline.run(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store,
        role="growth", persona=personas.get("growth"),
    )
    assert [r.policy_id for r in card.redactions] == ["fin.rail_detail"]
    assert "fin.rail_detail" in card.summary
    assert "payment_rail" in card.summary


def test_the_redaction_line_is_not_hardcoded_prose(store):
    """policy_id and reason come off the AccessRule. If someone retypes them into
    narrate.py, changing the contract stops changing the card -- and the governance
    story becomes decoration."""
    card = pipeline.run(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store,
        role="growth", persona=personas.get("growth"),
    )
    reason = contracts.get("mrr_renewals").access[0].reason
    assert reason.rstrip(".") in card.summary


def test_an_entitled_reader_sees_no_redaction_language(store):
    card = pipeline.run(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store,
        role="analyst", persona=personas.get("analyst"),
    )
    assert card.redactions == []
    assert "redact" not in card.summary.lower()


def test_redaction_does_not_reorder_the_candidates(store):
    """Entitlement hides CUTS, not candidates. The scores DO move -- the focal cohort
    legitimately changes, so hypothesis.rank scores against a different slice
    (0.700 -> 0.627 for deploy_sepa_v214). What must not move is the candidate set or
    its order: a policy that silently promoted a different cause would be a security
    hole dressed as a feature.
    """
    a = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="analyst")
    g = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="growth")
    assert [h.event.event_id for h in a.ranked] == [h.event.event_id for h in g.ranked]
    assert [h.event.event_id for h in a.rejected] == [h.event.event_id for h in g.rejected]


def test_entitlement_does_not_trigger_abstention(store):
    """Measured: growth's top candidate still clears SCORE_FLOOR. If this ever goes
    red, a redacted reader is being shown the 'no connected change explains it' card,
    which would blame the data for what policy did."""
    g = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="growth")
    assert g.no_confident_cause is False
    assert g.ranked[0].total >= config.SCORE_FLOOR


def test_the_abstention_card_also_carries_its_redactions(store):
    """Task 7 makes the abstention path reachable in the UI. A redacted reader who
    lands there must still see WHY their view is shallow -- otherwise the missing
    depth reads as the engine failing rather than as policy."""
    payload = pipeline.diagnose(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="growth"
    )
    card = narrate.narrate(payload, persona=personas.get("growth"), no_confident_cause=True)
    assert card.no_confident_cause is True
    assert [r.policy_id for r in card.redactions] == ["fin.rail_detail"]
    assert "fin.rail_detail" in card.summary
