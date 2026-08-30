"""Beta-Bernoulli priors over (event_type, metric) -- the feedback loop.

Alpha and beta are derived by COUNTING rows in `verdict` at read time rather than kept
in a separate state table, so the prior is always auditable against the labels that
produced it. There is no model to retrain and no state to drift: delete a verdict and
the prior it moved goes back where it was.

**The prior goes through `Store.q` like every other number.** It is the fifth scoring
component and it renders on the hypothesis card, so it needs a replayable `query_id`
for the same reason the other four do. Reading it with a bare `con.execute` -- which is
what this module used to do -- made P the one number on screen a reader could not open,
which is exactly the hole the whole product exists to close.

`record` writes the analyst's verdict and then invalidates the cached count, because
`q()` memoises and `verdict` is the only table the UI writes to.
"""

from __future__ import annotations

from datetime import datetime

from ledgerlens.models import stable_id
from ledgerlens.store import Store

# Constant, not interpolated with the event type: `Store.invalidate` matches on it
# exactly, and the parameters already distinguish one prior's query_id from another's.
PRIOR_LABEL = "learned prior"

# What counts as evidence against. "correct" means the analyst supplied a different
# cause, which is a rejection of this one that happens to carry a replacement.
_AGAINST = ("reject", "correct")


def counts(store: Store | None, event_type: str, metric: str) -> tuple[int, int, str]:
    """(confirmations, rejections, query_id) for this event type on this metric.

    Returns zeros and an empty query_id when there is no store -- the pure-scoring
    tests construct hypotheses without one, and a prior with no evidence behind it is
    genuinely 0.5 rather than an error.
    """
    if store is None:
        return 0, 0, ""
    frame, query_id = store.q(
        "SELECT verdict, count(*) AS n FROM verdict "
        "WHERE event_type = $e AND metric = $m GROUP BY verdict",
        {"e": event_type, "m": metric},
        label=PRIOR_LABEL,
    )
    confirms = rejects = 0
    for row in frame.to_dict("records"):
        if row["verdict"] == "confirm":
            confirms += int(row["n"])
        elif row["verdict"] in _AGAINST:
            rejects += int(row["n"])
    return confirms, rejects, query_id


def prior(store: Store | None, event_type: str, metric: str) -> tuple[float, str]:
    """Beta(alpha, beta) posterior mean, with the query that produced it.

    alpha = beta = 1 -> 0.5 with no evidence, which is deliberately uninformative: at
    weight 0.05 the prior can only ever break a near-tie, and `SCORE_FLOOR` is applied
    to the total. It sharpens a ranking; it never gates one.
    """
    confirms, rejects, query_id = counts(store, event_type, metric)
    alpha, beta = 1 + confirms, 1 + rejects
    return alpha / (alpha + beta), query_id


def record(
    store: Store,
    anomaly_id: str,
    hypothesis_id: str,
    event_type: str,
    metric: str,
    verdict: str,
    corrected_cause: str | None = None,
) -> None:
    """Write one analyst verdict, then invalidate the cached prior it changes.

    Without the invalidation the loop is silently open: the row lands in `verdict`, and
    the next diagnosis reads the memoised count from before it and reports an unchanged
    P. The bug would look exactly like "feedback does nothing", which is worse than not
    shipping the feature.
    """
    now = datetime.now()
    store.con.execute(
        "INSERT OR REPLACE INTO verdict VALUES ($vid, $aid, $hid, $et, $m, $v, $cc, $ts)",
        {
            "vid": stable_id("v", anomaly_id, hypothesis_id, verdict, now.isoformat()),
            "aid": anomaly_id,
            "hid": hypothesis_id,
            "et": event_type,
            "m": metric,
            "v": verdict,
            "cc": corrected_cause,
            "ts": now,
        },
    )
    store.invalidate(PRIOR_LABEL)
