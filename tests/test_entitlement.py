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
