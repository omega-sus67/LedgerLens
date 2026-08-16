from __future__ import annotations

from datetime import date

import pytest

import config
from ledgerlens.ledger import symptoms
from ledgerlens.models import Window

WINDOW = Window(start=date(2026, 8, 3), end=date(2026, 8, 16))


@pytest.fixture(scope="module")
def clusters(store):
    return symptoms.cluster(store, WINDOW)


def test_events_are_all_deterministic(store):
    events = store.events()
    assert len(events) == 13
    assert all(e.extraction == "deterministic" for e in events)
    assert all(e.confidence == 1.0 for e in events)


def test_true_cause_blast_radius_is_declared_not_inferred(store):
    ev = next(e for e in store.events() if e.event_id == "deploy_sepa_v214")
    assert ev.blast_radius == {"region": ["DACH"], "payment_rail": ["sepa"]}
    assert ev.source == "github"


def test_campaign_blast_radius_omits_undeclared_dimensions(store):
    """The decoy's radius is region-only because the campaign calendar declares only
    a geo. The omission is the point: it makes the radius wide, which is what the C
    component and the segment-sibling control both go on to punish."""
    ev = next(e for e in store.events() if e.event_id == "campaign_dach_cut")
    assert ev.blast_radius == {"region": ["DACH"]}
    assert "payment_rail" not in ev.blast_radius
    assert "segment" not in ev.blast_radius


def test_wildcard_region_becomes_unconstrained(store):
    ev = next(e for e in store.events() if e.event_id == "deploy_billing_ui_v9")
    assert ev.blast_radius == {}


def test_symptom_spike_is_the_only_surviving_cluster(clusters):
    assert len(clusters) == 1
    c = clusters[0]
    assert c.key == "ERR_SEPA_504"
    assert c.lift >= config.SYMPTOM_MIN_LIFT


def test_prose_tickets_join_the_coded_cluster(clusters):
    """Half the injected tickets never mention an error code -- they describe the
    failure in prose. Recovering them is what the clustering exists to do."""
    assert clusters[0].volume == config.INJECTED_TICKETS  # all 42: 21 coded + 21 prose


def test_symptom_cohort_matches_the_incident(clusters, truth):
    assert clusters[0].cohort == {"region": ["DACH"], "segment": ["Enterprise"]}
    assert clusters[0].first_seen == date.fromisoformat(truth["onset"])


def test_baseline_chatter_does_not_clear_the_lift_floor(store):
    """Ordinary ticket noise must not look like a symptom. This is the unit fix on
    spec 8.3: comparing a window total against a per-day mean inflates every lift by
    the window length and would surface all four baseline keys."""
    keys = {c.key for c in symptoms.cluster(store, WINDOW)}
    assert not ({"ERR_TIMEOUT", "BILLING_Q", "LOGIN", "FEATURE_REQ"} & keys)


def test_tokenizer_drops_digits_and_stopwords():
    assert symptoms.tokenize("ERR_SEPA_504") == ["err", "sepa"]
    assert "the" not in symptoms.tokenize("the gateway timed out")


def test_derived_key_is_stable_across_prose_variants(store):
    """Novel tokens rank top because IDF is measured against the pre-incident
    corpus, so unrelated prose about the same failure keys consistently."""
    rows = store.con.execute(
        "SELECT subject, error_code, created_at FROM ticket"
    ).fetchall()
    pre = [
        {"subject": s, "error_code": e}
        for s, e, ts in rows
        if ts.date() < WINDOW.start
    ]
    df, n = symptoms._corpus_df(pre)
    for subject in ["SEPA direct debit timeout during renewal charge", "Failing SEPA direct debit timeout"]:
        key = symptoms.derive_key(subject, df, n)
        assert "sepa" in key and "debit" in key
