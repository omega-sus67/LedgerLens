"""The demo script's numbers are load-bearing, exactly like the README's.

`tests/test_docs.py` exists because a judge who runs the suite and sees a different
number has been handed a reason to doubt every other figure in the repo. The demo
video is the same exposure with a worse failure mode: a figure that drifts after
recording cannot be corrected without re-shooting, and nobody discovers it until it
is on camera in front of the people scoring it.

So `docs/demo_script.md` carries a "Verified figures" table, and this module asserts
every row of it against a live diagnosis. Edit the app, not the table -- if a value
stops matching, this goes red and names the beat that has to be re-recorded.

What is deliberately NOT asserted here: the telemetry absolutes and every duration.
`docs/telemetry_decisions.md` is explicit that the query counts move whenever a
feature adds a query and that only the RATIO is durable, and that a duration must
never be asserted because cold-vs-warm is ~2.6x and fixture warmth is test-order
dependent. Pinning either would make this file fail for a reason that is not a demo
problem -- which is the fastest way to teach someone to ignore it.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

import config
from ledgerlens import narrate, personas, pipeline

AS_OF = date(2026, 8, 17)
SCRIPT = Path(config.ROOT) / "docs" / "demo_script.md"

# Display rounding is the only slack allowed. The card prints -1.3% for a measured
# -1.31 and -31.0% for a measured -30.96, so a percentage may differ from the table
# by less than a tenth of a point -- and nothing more.
PCT_TOL = 0.1
SCORE_TOL = 0.01
ABS_TOL = 1.0


def _figures() -> dict[str, str]:
    """Parse the `| key | value | appears in |` table out of the script.

    Anchored on the "## Verified figures" heading so the many other tables in the
    document (the cut list, the troubleshooting matrix) cannot leak rows in.
    """
    text = SCRIPT.read_text()
    section = text.split("## Verified figures", 1)
    assert len(section) == 2, "demo_script.md has lost its 'Verified figures' section"
    out: dict[str, str] = {}
    for row in re.finditer(r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|", section[1], re.M):
        out[row.group(1)] = row.group(2).strip()
    assert out, "the Verified figures table parsed to zero rows"
    return out


@pytest.fixture(scope="module")
def figures() -> dict[str, str]:
    return _figures()


@pytest.fixture(scope="module")
def live(store) -> dict[str, object]:
    """One live run per shape the script films, reduced to the quoted figures."""
    analyst = pipeline.diagnose("mrr_renewals", AS_OF, store=store)
    card = narrate.narrate(analyst, personas.get("analyst"))
    growth = pipeline.diagnose("mrr_renewals", AS_OF, store=store, role="growth")
    growth_card = narrate.narrate(growth, personas.get("growth"))
    dropped = pipeline.diagnose(
        "mrr_renewals", AS_OF, store=store, drop_sources=frozenset({"github"})
    )

    top = analyst.ranked[0]
    decoy = analyst.rejected[0]
    flat = next(c for c in decoy.controls if c.decisive)
    second = next(c for c in decoy.controls if "new_logo" in c.metric)
    p2 = next(a for a in card.actions if "new_logo_bookings" in (a.basis or ""))

    return {
        "root_delta_pct": analyst.root.delta_pct,
        "seasonal_pct": analyst.seasonal_pct,
        "focal_delta_pct": analyst.focal.delta_pct,
        "focal_delta_abs": abs(analyst.focal.delta_abs),
        "candidate_count": len(analyst.ranked) + len(analyst.rejected),
        "top_event": top.event.event_id,
        "top_score": top.total,
        "top_controls_passed": sum(1 for c in top.controls if c.passed),
        "decoy_event": decoy.event.event_id,
        "decoy_score": decoy.total,
        "decoy_control_flat_pct": flat.observed_delta_pct,
        "second_finding_pct": second.observed_delta_pct,
        "growth_focal_delta_pct": growth.focal.delta_pct,
        "growth_focal_delta_abs": abs(growth.focal.delta_abs),
        "growth_top_score": growth.ranked[0].total,
        "redaction_policy": growth_card.redactions[0].policy_id,
        "redaction_dim": growth_card.redactions[0].dim,
        "abstain_closest_score": max(
            h.total for h in dropped.ranked + dropped.rejected
        ),
        "abstain_floor": config.SCORE_FLOOR,
        "_p2_basis": p2.basis,
    }


def _tolerance(key: str) -> float:
    if key.endswith("_abs"):
        return ABS_TOL
    if "score" in key or key == "abstain_floor":
        return SCORE_TOL
    return PCT_TOL


def test_the_table_covers_every_figure_the_script_films(figures, live):
    """A row added to the script's table with no live counterpart is a typo that
    would otherwise pass silently, asserting nothing."""
    unknown = set(figures) - {k for k in live if not k.startswith("_")}
    assert not unknown, f"table rows with nothing to check them against: {unknown}"


@pytest.mark.parametrize("key", sorted(_figures()))
def test_every_quoted_figure_matches_a_live_diagnosis(key, figures, live):
    """THE test. Each row of the script's table, against what the app just produced."""
    claimed_raw = figures[key]
    actual = live[key]

    if isinstance(actual, str):
        assert claimed_raw == actual, f"beat quotes {claimed_raw!r}, app says {actual!r}"
        return

    claimed = float(claimed_raw)
    tol = _tolerance(key)
    assert actual == pytest.approx(claimed, abs=tol), (
        f"{key}: script quotes {claimed}, live diagnosis gives {actual:.4f} "
        f"(tolerance {tol}). Re-record the beat, or fix the app -- do not edit the "
        f"table to match a regression."
    )


def test_the_second_finding_is_still_on_the_card(live):
    """Beat 4 exists only because the decoy is innocent HERE and guilty THERE. If the
    P2 action stops carrying its own query id, the beat is unfilmable as scripted."""
    basis = live["_p2_basis"]
    assert "new_logo_bookings" in basis
    assert re.search(r"q_[0-9a-f]+", basis), "the second finding lost its query_id"


def test_the_script_never_pins_a_telemetry_absolute_or_a_duration(figures):
    """`docs/telemetry_decisions.md`: the query counts move whenever a feature adds a
    query, and a duration is test-order dependent. Either one in this table turns a
    green suite red for a reason that has nothing to do with the demo -- and a check
    that cries wolf is a check people learn to skip."""
    banned = [k for k in figures if re.search(r"quer|_ms|latency|token|cost", k)]
    assert not banned, (
        f"these belong on screen in beat 12, not pinned in the table: {banned}"
    )


def test_every_table_row_names_a_beat_that_exists(figures):
    """The `appears in` column is the re-record instruction. A row pointing at a beat
    that was cut sends someone to a scene that is not in the script."""
    section = SCRIPT.read_text().split("## Verified figures", 1)[1]
    beats = {int(m) for m in re.findall(r"^## Beat (\d+)", SCRIPT.read_text(), re.M)}
    for row in re.finditer(r"^\|\s*`([^`]+)`\s*\|[^|]+\|\s*([^|]+?)\s*\|", section, re.M):
        named = {int(m) for m in re.findall(r"\d+", row.group(2))}
        missing = named - beats
        assert not missing, f"{row.group(1)} points at absent beat(s) {missing}"
