"""Shared fixtures. This is the ONLY place `ground_truth.json` may be read --
nothing inside the `ledgerlens/` package is allowed to see it (spec 4.3)."""

from __future__ import annotations

import json

import pytest

import config
from ledgerlens.gen_data import generate
from ledgerlens.store import Store


@pytest.fixture(scope="session")
def truth() -> dict:
    if not (config.DATA_DIR / "ground_truth.json").exists():
        generate()
    return json.loads((config.DATA_DIR / "ground_truth.json").read_text())


@pytest.fixture(scope="session")
def store(truth) -> Store:
    s = Store()
    s.load_all(config.DATA_DIR)
    # `verdict` is the ONLY table the running app writes to, and data/ledgerlens.duckdb
    # persists between runs -- so a verdict left by a previous session would silently
    # shift the learned prior, and with it every P component and every total. The
    # acceptance tests assert exact scores against an UNINFORMED prior, so the suite
    # has to start from one. Truncating here rather than trusting cleanup makes the
    # suite hermetic even after a crashed run or a manual click in the UI.
    s.con.execute("DELETE FROM verdict")
    yield s
    s.close()


@pytest.fixture
def clean_verdicts(store):
    """For tests that deliberately record a verdict against the shared database.

    Restores the uninformed prior afterwards, and drops the memoised count with it --
    leaving the row behind would move `test_true_cause_ranks_first`'s 0.700 by 0.008
    against its 0.01 tolerance, which is a flake that only fires on the NEXT run.
    """
    from ledgerlens import learning

    yield store
    store.con.execute("DELETE FROM verdict")
    store.invalidate(learning.PRIOR_LABEL)
