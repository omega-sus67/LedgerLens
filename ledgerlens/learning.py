"""Beta-Bernoulli priors over (event_type, metric).

Alpha and beta are derived by COUNTING rows in `verdict` at read time rather than
kept in a separate state table, so the prior is always auditable against the labels
that produced it.

Only `prior` is wired into the pipeline for this build; `record` exists so the UI can
close the loop when the confirm/reject controls are built.
"""

from __future__ import annotations

from datetime import datetime

from ledgerlens.models import stable_id
from ledgerlens.store import Store


def prior(store: Store | None, event_type: str, metric: str) -> float:
    """Beta(alpha, beta) mean, initialised alpha = beta = 1 -> 0.5."""
    alpha = beta = 1
    if store is not None:
        rows = store.con.execute(
            "SELECT verdict, count(*) FROM verdict WHERE event_type = $e AND metric = $m "
            "GROUP BY verdict",
            {"e": event_type, "m": metric},
        ).fetchall()
        for verdict, n in rows:
            if verdict == "confirm":
                alpha += n
            elif verdict in ("reject", "correct"):
                beta += n
    return alpha / (alpha + beta)


def record(
    store: Store,
    anomaly_id: str,
    hypothesis_id: str,
    event_type: str,
    metric: str,
    verdict: str,
    corrected_cause: str | None = None,
) -> None:
    store.con.execute(
        "INSERT OR REPLACE INTO verdict VALUES ($vid, $aid, $hid, $et, $m, $v, $cc, $ts)",
        {
            "vid": stable_id("v", anomaly_id, hypothesis_id, verdict, datetime.now().isoformat()),
            "aid": anomaly_id,
            "hid": hypothesis_id,
            "et": event_type,
            "m": metric,
            "v": verdict,
            "cc": corrected_cause,
            "ts": datetime.now(),
        },
    )
