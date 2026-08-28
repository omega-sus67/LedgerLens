"""Smoke test for the UI. Cheap insurance against a blank screen on stage."""

from __future__ import annotations

from pathlib import Path

import pytest

from streamlit.testing.v1 import AppTest

import config

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(scope="module")
def app(truth):
    return AppTest.from_file(APP_PATH, default_timeout=180).run()


def test_page_renders_without_exceptions(app):
    assert app.exception == []


def test_headline_names_the_cause(app):
    assert "deploy_sepa_v214" in app.title[0].value


def test_header_separates_seasonality_from_the_real_signal(app):
    """The 'meaningful change vs normal noise' requirement, visible in the first two
    seconds: the calendar explains about a point of it, the rest is the incident."""
    text = " ".join(m.value for m in app.markdown)
    assert "August seasonality" in text
    assert "Unexplained" in text


def test_rejected_decoy_is_visibly_rejected(app):
    banners = [e.value for e in app.error]
    assert any("REJECTED" in b for b in banners)
    assert any("Mid" in b and "SMB" in b for b in banners)


def test_every_hypothesis_shows_a_score(app):
    scores = [m.value for m in app.metric if m.label == "score"]
    assert len(scores) == 5
    assert scores[0] == "0.700"


def test_weights_are_visible_to_the_analyst(app):
    """Spec 2: the weights are displayed, not hidden. A number a judge cannot audit
    is a number that costs points."""
    assert any("Scoring weights" in h.value for h in app.sidebar.subheader)
