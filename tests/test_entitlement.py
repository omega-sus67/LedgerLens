"""Role-based entitlement: redaction WITH provenance.

The point is not that growth sees less. It is that growth is TOLD it sees less, by
which policy, and why -- a refusal that names itself is governance; a silently shorter
answer is a bug.

Closes Minimum Prototype Expectation row 7. Full rationale in
docs/roles_decisions.md; the plan this file was written against is
taskflow/roles_tasks.md.
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
