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
    yield s
    s.close()
