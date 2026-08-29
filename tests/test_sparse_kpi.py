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
