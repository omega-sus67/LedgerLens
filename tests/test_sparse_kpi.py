"""The sparse-history KPI, end to end.

The first test in this file is the one that matters most: it asserts the two
pre-existing metrics are bit-identical after a third was added to the generator.
`gen_data.py` uses one sequential RNG stream, so an incautious insertion shifts every
downstream draw -- tickets, symptom clusters, and the acceptance numbers with them.

If a fingerprint fails, fix the generator. NEVER update the hash.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

import pandas as pd
import pytest

import config
from ledgerlens import anomaly, contracts, pipeline
from ledgerlens.models import Window

EXISTING = ["mrr_renewals", "new_logo_bookings"]

# Pinned against the pre-task-3 generator, verified reproducible from a clean
# `python -m ledgerlens.gen_data` run on 2026-08-29.
PRISTINE = {
    "mrr_renewals": "ed337da45766a707",
    "new_logo_bookings": "292eb8d77671d2e9",
}


def _fingerprint(metric: str) -> str:
    df = pd.read_parquet(config.DATA_DIR / "metrics.parquet")
    df = df[df["metric_name"] == metric].sort_values(
        ["date", "region", "segment", "payment_rail", "product"]
    )
    return hashlib.sha256(df["value"].round(6).to_numpy().tobytes()).hexdigest()[:16]


@pytest.mark.parametrize("metric", EXISTING)
def test_existing_metrics_are_bit_identical(truth, metric):
    """If this fails, the new metric is drawing from the shared RNG stream --
    give it its own `default_rng(SEED_SPARSE)`, do not update the hash."""
    assert _fingerprint(metric) == PRISTINE[metric]


def test_sparse_metric_has_short_history(truth):
    df = pd.read_parquet(config.DATA_DIR / "metrics.parquet")
    sparse = df[df["metric_name"] == "payment_attempts"]
    assert not sparse.empty
    assert sparse["date"].min() == config.SPARSE_LAUNCH


def test_sparse_history_is_below_the_detection_warmup(truth):
    """The whole point: too young to auto-detect."""
    days = (pipeline.DEFAULT_AS_OF - config.SPARSE_LAUNCH).days + 1
    assert days < contracts.thresholds("payment_success_rate").warmup_days


def test_sparse_history_still_supports_a_manual_window(truth):
    """...but old enough that fit_pre_window's 30-day minimum is met, or the KPI
    could do nothing at all. This is why "~45 days" does not work."""
    window_start = pipeline.DEFAULT_AS_OF - timedelta(days=13)
    pre_days = (window_start - config.SPARSE_LAUNCH).days
    assert pre_days >= 30, "manual path needs fit_pre_window's 30-day floor"


@pytest.fixture(scope="module")
def sparse_card(store):
    """The manual path: detection declined, so the analyst supplies the window."""
    return pipeline.run(
        "payment_success_rate",
        pipeline.DEFAULT_AS_OF,
        store=store,
        cohort={"region": ["DACH"], "payment_rail": ["sepa"]},
        window=Window(start=date(2026, 8, 4), end=date(2026, 8, 17)),
    )


def test_manual_path_produces_a_full_card(sparse_card):
    """Declining to DETECT is not declining to help."""
    assert sparse_card.causal_chain
    assert sparse_card.actions
    assert pipeline.card_query_ids(sparse_card)


def test_rate_kpi_is_never_formatted_as_dollars(sparse_card):
    """_money() on a rate renders '-$0.07'. The contract carries unit='rate'."""
    text = f"{sparse_card.headline} {sparse_card.summary} "
    text += " ".join(a.expected_impact + a.action for a in sparse_card.actions)
    text += " ".join(s.observed for s in sparse_card.causal_chain)
    assert "$" not in text


def test_card_states_the_history_limitation_up_front(sparse_card):
    """The decline must be legible. A blank success box is the failure mode."""
    assert "insufficient history" in sparse_card.summary.lower()
    assert "manual" in sparse_card.summary.lower()


def test_sparse_card_widens_its_own_uncertainty(sparse_card):
    """55 days of history is not 400. Actions grounded on it must say so."""
    assert any("warmup" in a.monitoring.lower() or "short history" in a.monitoring.lower()
               for a in sparse_card.actions)


def test_established_kpi_carries_no_sparse_preamble(store):
    """The banner must not leak onto KPIs that do not need it."""
    card = pipeline.run("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    assert "insufficient history" not in card.summary.lower()
    assert "$" in card.summary
