"""The feedback loop -- Round 2 Objective 7.

The prior is the fifth scoring component and the only one an analyst can move. These
tests pin the two properties that make it safe to ship: it is DERIVED from rows rather
than kept as model state, and at weight 0.05 it can sharpen a ranking without ever
deciding one.

Every test uses its own Store on a temp path. The session-scoped `store` fixture is
shared, and a verdict written into it would leak into the acceptance tests' scores --
which is exactly the kind of hidden coupling `SEED` discipline exists to prevent.
"""

from __future__ import annotations

import pytest

import config
from ledgerlens import hypothesis, learning, pipeline
from ledgerlens.store import Store

AS_OF = pipeline.DEFAULT_AS_OF


@pytest.fixture
def scratch(tmp_path, truth):
    """A private copy of the database, loaded from the same deterministic parquet."""
    s = Store(tmp_path / "scratch.duckdb")
    s.init_schema()
    s.load_all(config.DATA_DIR)
    yield s
    s.close()


def _record(store, kind, n=1, event_type="deploy", metric="mrr_renewals"):
    for i in range(n):
        learning.record(
            store,
            anomaly_id=f"a{i}",
            hypothesis_id=f"h{i}",
            event_type=event_type,
            metric=metric,
            verdict=kind,
        )


# ------------------------------------------------------------------ the prior


def test_no_verdicts_is_an_uninformative_half(scratch):
    value, query_id = learning.prior(scratch, "deploy", "mrr_renewals")
    assert value == 0.5
    assert query_id, "even a prior with no evidence must carry the query that showed none"


def test_prior_without_a_store_is_half_and_carries_no_query(): 
    """Pure scoring paths construct hypotheses with no database. A prior with no
    evidence behind it is genuinely 0.5, not an error."""
    assert learning.prior(None, "deploy", "mrr_renewals") == (0.5, "")


def test_a_confirmation_raises_the_prior_and_a_rejection_lowers_it(scratch):
    _record(scratch, "confirm", 3)
    up, _ = learning.prior(scratch, "deploy", "mrr_renewals")
    assert up == pytest.approx(4 / 5)

    _record(scratch, "reject", 3)
    back, _ = learning.prior(scratch, "deploy", "mrr_renewals")
    assert back == pytest.approx(0.5), "equal evidence both ways returns to uninformative"


def test_a_correction_counts_against_the_hypothesis_it_corrects(scratch):
    """'correct' supplies a different cause, which is a rejection carrying a
    replacement -- not a third neutral category."""
    _record(scratch, "correct", 2)
    value, _ = learning.prior(scratch, "deploy", "mrr_renewals")
    assert value < 0.5


def test_the_prior_is_scoped_to_event_type_and_metric(scratch):
    _record(scratch, "confirm", 4, event_type="deploy", metric="mrr_renewals")
    assert learning.prior(scratch, "deploy", "mrr_renewals")[0] > 0.5
    assert learning.prior(scratch, "campaign", "mrr_renewals")[0] == 0.5
    assert learning.prior(scratch, "deploy", "new_logo_bookings")[0] == 0.5


def test_the_prior_is_derived_from_rows_not_kept_as_state(scratch):
    """Delete the evidence and the prior goes back exactly where it was. This is the
    whole argument for counting at read time instead of maintaining alpha/beta."""
    _record(scratch, "confirm", 5)
    assert learning.prior(scratch, "deploy", "mrr_renewals")[0] == pytest.approx(6 / 7)
    scratch.con.execute("DELETE FROM verdict")
    scratch.invalidate(learning.PRIOR_LABEL)
    assert learning.prior(scratch, "deploy", "mrr_renewals")[0] == 0.5


# ------------------------------------------------------- the cache invalidation


def test_recording_a_verdict_invalidates_the_memoised_count(scratch):
    """THE bug this feature would otherwise ship with. `q()` memoises and never
    expires; `verdict` is the only table the UI writes to. Without the invalidation the
    row lands, the prior moves in the database, and the reader sees an unchanged P --
    which looks exactly like 'feedback does nothing'."""
    before, _ = learning.prior(scratch, "deploy", "mrr_renewals")
    assert before == 0.5
    _record(scratch, "confirm", 1)
    after, _ = learning.prior(scratch, "deploy", "mrr_renewals")
    assert after > before, "the prior must move without opening a new Store"


def test_invalidate_only_drops_the_label_it_was_given(scratch):
    """A blunt cache clear would work and would make every later diagnosis report cold
    execution counts, quietly corrupting the telemetry panel."""
    scratch.q("SELECT 1 AS x", label="unrelated")
    learning.prior(scratch, "deploy", "mrr_renewals")
    cached_before = len(scratch._q_cache)
    dropped = scratch.invalidate(learning.PRIOR_LABEL)
    assert dropped == 1
    assert len(scratch._q_cache) == cached_before - 1


# ----------------------------------------------------------- effect on ranking


def test_the_prior_is_auditable_like_every_other_number(scratch):
    """P used to be read with a bare con.execute, which made it the one component on
    the card a reader could not open. It is the fifth score and it renders on screen,
    so it carries a query_id for the same reason the other four do."""
    payload = pipeline.diagnose("mrr_renewals", AS_OF, store=scratch)
    top = payload.ranked[0]
    _, p_query = learning.prior(scratch, top.event.event_type, "mrr_renewals")
    assert p_query in top.query_ids
    assert p_query in pipeline.card_query_ids(pipeline.run("mrr_renewals", AS_OF, store=scratch))
    sql, _, _ = scratch.replay(p_query)
    assert "verdict" in sql


def test_feedback_moves_scores_without_overturning_the_verdict(scratch):
    """The safety property. Weight is 0.05, so confirming the true cause five times
    lifts its score without disturbing the ORDER -- and, critically, without rescuing
    the rejected decoy, whose rejection is a control result the prior cannot outvote.

    Order is asserted, never scores; scores legitimately move, that is the point.
    """
    before = pipeline.diagnose("mrr_renewals", AS_OF, store=scratch)
    top = before.ranked[0]
    assert top.event.event_id == "deploy_sepa_v214"

    _record(scratch, "confirm", 5, event_type=top.event.event_type)
    after = pipeline.diagnose("mrr_renewals", AS_OF, store=scratch)

    assert [h.event.event_id for h in after.ranked] == [h.event.event_id for h in before.ranked]
    assert after.ranked[0].scores.P > before.ranked[0].scores.P
    assert after.ranked[0].total > before.ranked[0].total
    assert [h.event.event_id for h in after.rejected] == [
        h.event.event_id for h in before.rejected
    ], "a learned prior must never rescue a hypothesis a control killed"


def test_the_prior_cannot_lift_a_candidate_over_the_score_floor_alone(scratch):
    """P is weighted 0.05, so its full range moves a total by at most 0.05. A candidate
    that is 0.10 below the floor cannot be confirmed into confidence."""
    assert config.SCORE_WEIGHTS["P"] == 0.05
    _record(scratch, "confirm", 200, event_type="feature_flag")
    payload = pipeline.diagnose("mrr_renewals", AS_OF, store=scratch)
    flags = [h for h in payload.ranked if h.event.event_type == "feature_flag"]
    for h in flags:
        assert h.scores.P > 0.9, "the prior really is saturated"
        assert h.total < config.SCORE_FLOOR, "and it still cannot manufacture confidence"
