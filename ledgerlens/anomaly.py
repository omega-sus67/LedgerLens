"""Detection, measurement and hierarchical drill-down.

Two baselines, deliberately. They answer different questions and conflating them is
a real bug:

  Pass A (`scan_for_onset`)  -- WHERE did it break? Causal, trailing, cheap. Accuracy
      barely matters because the signal is ~14 sigma.
  Pass B (`evaluate`)        -- HOW BIG is it? A model fitted on the pre-window ONLY
      and then frozen and extrapolated across the anomaly window.

Using pass A's trailing rolling median to *measure* would be wrong: by the end of a
14-day window half of the trailing 28 days are themselves anomalous, the baseline
sags toward the new regime, and the reported delta shrinks from -8.2% to about -6.6%
-- outside the acceptance band, for reasons that have nothing to do with the data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy import stats

import config
from ledgerlens import contracts
from ledgerlens.models import (
    Anomaly,
    Cohort,
    Window,
    canonical_cohort_key,
    stable_id,
)
from ledgerlens.store import Store

EPS = 1e-9


@dataclass(frozen=True)
class Eval:
    actual: float
    expected: float
    delta_abs: float
    delta_pct: float
    residual_z: float
    rows_per_day: float = 0.0


# ------------------------------------------------------------------- baseline


def _weekday_factors(values: pd.Series, trend: np.ndarray) -> dict[int, float]:
    ratio = values.to_numpy() / np.maximum(trend, EPS)
    out: dict[int, float] = {}
    weekdays = values.index.weekday
    for wd in range(7):
        sel = ratio[weekdays == wd]
        out[wd] = float(np.median(sel)) if len(sel) else 1.0
    return out


def fit_pre_window(pre: pd.Series) -> tuple[np.ndarray, dict[int, float], float, float] | None:
    """Fit level+slope+weekday shape on the pre-window and return the residual scale.

    Theil-Sen rather than a flat 28-day median: the series carries a mild upward
    trend, so a level fitted on a window whose centre of mass sits ~3 weeks before
    the anomaly reads about 0.8% low -- and 0.8pp against a 0.8pp-wide acceptance
    band is fatal. Theil-Sen also shrugs off the quarter-end spikes that can fall
    inside the pre-window (3% contamination against a 29% breakdown point).
    """
    pre = pre.dropna()
    if len(pre) < 30 or float(pre.sum()) <= 0:
        return None
    x = np.arange(len(pre), dtype=float)
    slope, intercept, _, _ = stats.theilslopes(pre.to_numpy(dtype=float), x)
    trend = intercept + slope * x
    if np.any(trend <= 0):
        return None
    wf = _weekday_factors(pre, trend)
    expected_pre = trend * np.array([wf[wd] for wd in pre.index.weekday])
    resid = pre.to_numpy(dtype=float) - expected_pre
    med = float(np.median(resid))
    mad = float(np.median(np.abs(resid - med)))
    return np.array([intercept, slope]), wf, med, mad


def project(coef: np.ndarray, wf: dict[int, float], n_pre: int, index: pd.DatetimeIndex) -> np.ndarray:
    """Extrapolate the frozen pre-window model onto `index` (which follows the pre-window)."""
    intercept, slope = coef
    offsets = np.arange(n_pre, n_pre + len(index), dtype=float)
    return (intercept + slope * offsets) * np.array([wf[wd] for wd in index.weekday])


def evaluate(series: pd.Series, window: Window, agg: str = "sum") -> Eval | None:
    """Measure `window` against a model fitted on the PRE-window only.

    `agg="ratio"` changes only the REPORTED level, never the fit: a rate's window
    figure is the mean of its daily values, not their sum -- summing 14 daily rates
    gives ~13.7, which is meaningless on a card. delta_pct is identical either way,
    since dividing actual and expected by the same day count cannot change their
    ratio, so only actual, expected and delta_abs are affected.

    The pre-window must exclude the anomaly. If median/MAD are taken over the window
    itself, every day is ~8% low, the residual median is ~-8%, and z collapses to
    roughly zero -- the anomaly quietly defines its own normal. `test_anomaly.py`
    asserts exactly this contrast.
    """
    start = pd.Timestamp(window.start)
    end = pd.Timestamp(window.end)
    pre = series[series.index < start]
    win = series[(series.index >= start) & (series.index <= end)].dropna()
    if win.empty:
        return None
    fit = fit_pre_window(pre)
    if fit is None:
        return None
    coef, wf, med, mad = fit

    n_pre = len(pre.dropna())
    expected_daily = project(coef, wf, n_pre, win.index)
    actual = float(win.sum())
    expected = float(expected_daily.sum())
    if expected <= 0:
        return None
    resid_daily = win.to_numpy(dtype=float) - expected_daily
    z_daily = 0.6745 * (resid_daily - med) / max(mad, EPS)

    if agg == "ratio":
        n = len(win)
        actual, expected = actual / n, expected / n

    return Eval(
        actual=actual,
        expected=expected,
        delta_abs=actual - expected,
        delta_pct=100.0 * (actual / expected - 1.0),
        residual_z=float(np.mean(z_daily)),
    )


# ------------------------------------------------------------------ detection


def scan_for_onset(series: pd.Series, th: contracts.Thresholds | None = None) -> date | None:
    """First day starting a run of `th.min_consecutive` breaching days.

    A day breaches when it is BOTH statistically extreme (robust z past `th.mad_z`)
    AND practically material (relative shortfall past `th.min_abs_delta_pct`). The
    second gate is a spec addition: without it the August seasonal dip sits close
    enough to the threshold that a run of two noisy days flags roughly one August in
    seven, turning the "no false flag on 2026-07-31" acceptance test into a coin flip.

    `th` defaults to the global constants, so a caller that predates per-KPI
    contracts sees identical behaviour.
    """
    th = th or contracts.Thresholds()
    s = series.dropna()
    if len(s) < th.warmup_days:
        return None

    roll = s.rolling(28, min_periods=14).median().shift(1)
    frame = pd.DataFrame({"s": s, "roll": roll})
    frame["ratio"] = frame["s"] / frame["roll"]
    frame["wd"] = frame.index.weekday
    frame["wf"] = frame.groupby("wd")["ratio"].transform(
        lambda x: x.rolling(8, min_periods=4).median().shift(1)
    )
    expected = frame["roll"] * frame["wf"]
    resid = frame["s"] - expected

    values = resid.to_numpy(dtype=float)
    exp_values = expected.to_numpy(dtype=float)
    flags = np.zeros(len(s), dtype=bool)
    for i in range(th.warmup_days, len(s)):
        if not np.isfinite(values[i]) or not np.isfinite(exp_values[i]) or exp_values[i] <= 0:
            continue
        pre = values[max(0, i - config.PRE_WINDOW_DAYS) : i]
        pre = pre[np.isfinite(pre)]
        if len(pre) < 30:
            continue
        med = np.median(pre)
        mad = np.median(np.abs(pre - med))
        z = 0.6745 * (values[i] - med) / max(mad, EPS)
        rel = 100.0 * values[i] / exp_values[i]
        flags[i] = z < -th.mad_z and rel < -th.min_abs_delta_pct

    run = 0
    for i, flagged in enumerate(flags):
        run = run + 1 if flagged else 0
        if run >= th.min_consecutive:
            return s.index[i - run + 1].date()
    return None


def _anomaly_from_eval(
    metric: str,
    cohort: Cohort,
    window: Window,
    onset: date,
    ev: Eval,
    query_id: str,
    contribution: float,
    depth: int,
    parent_id: str | None,
) -> Anomaly:
    return Anomaly(
        anomaly_id=stable_id("a", metric, canonical_cohort_key(cohort), window.start, window.end),
        metric=metric,
        cohort=cohort,
        window=window,
        onset=onset,
        actual=ev.actual,
        expected=ev.expected,
        delta_abs=ev.delta_abs,
        delta_pct=ev.delta_pct,
        residual_z=ev.residual_z,
        contribution=contribution,
        depth=depth,
        parent_id=parent_id,
        query_id=query_id,
        rows_per_day=ev.rows_per_day,
        bh_p=_z_to_p(ev.residual_z),
    )


def detect(store: Store, metric: str, as_of: date) -> Anomaly | None:
    """Root-level detection on the fully aggregated metric."""
    scan_start = as_of - timedelta(days=config.SCAN_DAYS)
    series, _ = store.series(metric, {}, scan_start, as_of)
    if series.empty:
        return None
    onset = scan_for_onset(series, contracts.thresholds(metric))
    if onset is None:
        return None

    end = min(onset + timedelta(days=config.WINDOW_LENGTH_DAYS - 1), as_of)
    window = Window(start=onset, end=end)
    full, query_id = store.series(
        metric, {}, onset - timedelta(days=config.PRE_WINDOW_DAYS), end
    )
    ev = evaluate(full, window, agg=contracts.get(metric).agg)
    if ev is None:
        return None
    return _anomaly_from_eval(metric, {}, window, onset, ev, query_id, 1.0, 0, None)


def measure(store: Store, metric: str, cohort: Cohort, window: Window) -> tuple[Eval | None, str]:
    """Evaluate an arbitrary cohort over an existing window. Never re-detects."""
    full, query_id = store.series(
        metric, cohort, window.start - timedelta(days=config.PRE_WINDOW_DAYS), window.end
    )
    return evaluate(full, window, agg=contracts.get(metric).agg), query_id


# ----------------------------------------------------------------- drill-down


def _z_to_p(z: float) -> float:
    return float(2.0 * (1.0 - stats.norm.cdf(abs(z))))


def _bh_mark(nodes: list[Anomaly], q: float = config.BH_FDR_Q) -> list[Anomaly]:
    """Benjamini-Hochberg across the children tested at one level.

    Labels only -- never gates. Sibling slices are subsets of one parent and so are
    positively dependent, which makes BH's guarantee approximate here; it is a
    principled sanity filter on branch selection, not the load-bearing rigor. The
    negative controls downstream carry that, and they need no distributional
    assumption at all.
    """
    if not nodes:
        return nodes
    order = sorted(range(len(nodes)), key=lambda i: nodes[i].bh_p)
    m = len(nodes)
    survived = [False] * m
    cutoff = -1
    for rank, i in enumerate(order, start=1):
        if nodes[i].bh_p <= rank / m * q:
            cutoff = rank
    for rank, i in enumerate(order, start=1):
        survived[i] = rank <= cutoff
    return [n.model_copy(update={"bh_survived": survived[i]}) for i, n in enumerate(nodes)]


def drill(store: Store, root: Anomaly, dims: list[str] | None = None) -> list[Anomaly]:
    """Breadth-first expansion, one dimension per level.

    At each level every unconstrained dimension is tested, then only the WINNING
    dimension's surviving children are kept and expanded. That bounds the search to
    the anomalous path instead of the full cross-product, and mirrors how an analyst
    actually drills: pick the dimension that explains the most, then go deeper.
    """
    dims = dims or config.DRILL_DIMS
    th = contracts.thresholds(root.metric)
    out = [root]
    frontier = [root]

    for depth in range(1, config.MAX_DRILL_DEPTH + 1):
        by_dim: dict[str, list[Anomaly]] = {}
        for node in frontier:
            # Near-zero denominators make contributions explode (spec 16 #4).
            if abs(node.actual - node.expected) < config.CONTRIB_DENOM_FLOOR * node.expected:
                continue
            for dim in [d for d in dims if d not in node.cohort]:
                for value in store.dim_universe(dim):
                    child_cohort = {**node.cohort, dim: [value]}
                    rows, _ = store.cohort_rows(child_cohort, node.window, root.metric)
                    rows_per_day = rows / max(node.window.days, 1)
                    # STRICT `<`. The true cohort has exactly 3 rows/day against a
                    # threshold of 3; `<=` would silently delete the answer.
                    if rows_per_day < config.MIN_SLICE_ROWS_PER_DAY:
                        continue
                    ev, query_id = measure(store, root.metric, child_cohort, node.window)
                    if ev is None:
                        continue
                    contribution = ev.delta_abs / (node.actual - node.expected)
                    if (
                        ev.residual_z < -th.mad_z
                        and contribution >= config.CONTRIBUTION_FLOOR
                    ):
                        ev = Eval(**{**ev.__dict__, "rows_per_day": rows_per_day})
                        by_dim.setdefault(dim, []).append(
                            _anomaly_from_eval(
                                root.metric,
                                child_cohort,
                                node.window,
                                node.onset,
                                ev,
                                query_id,
                                contribution,
                                depth,
                                node.anomaly_id,
                            )
                        )
        if not by_dim:
            break

        best_dim = max(
            by_dim,
            key=lambda d: (
                max(c.contribution for c in by_dim[d]),
                max(abs(c.delta_abs) for c in by_dim[d]),
                -dims.index(d),
            ),
        )
        kept = _bh_mark(
            sorted(by_dim[best_dim], key=lambda c: (-c.contribution, c.cohort[best_dim][0]))
        )
        out.extend(kept)
        frontier = kept

    return out


def focal(nodes: list[Anomaly]) -> Anomaly:
    """The deepest node with the strongest contribution product along its path."""
    by_id = {n.anomaly_id: n for n in nodes}
    memo: dict[str, float] = {}

    def path_contribution(node: Anomaly) -> float:
        if node.anomaly_id in memo:
            return memo[node.anomaly_id]
        parent = by_id.get(node.parent_id) if node.parent_id else None
        value = node.contribution * (path_contribution(parent) if parent else 1.0)
        memo[node.anomaly_id] = value
        return value

    return max(nodes, key=lambda n: (n.depth, path_contribution(n)))


def path_contribution(nodes: list[Anomaly], node: Anomaly) -> float:
    by_id = {n.anomaly_id: n for n in nodes}
    out = node.contribution
    cur = node
    while cur.parent_id and cur.parent_id in by_id:
        cur = by_id[cur.parent_id]
        out *= cur.contribution
    return out


# ------------------------------------------------------------------ seasonal


def seasonal_estimate(
    store: Store, metric: str, cohort: Cohort, ref_year: int = 2025, month: int = 8
) -> tuple[float, str]:
    """How much of the drop is just the calendar, measured from last year's data.

    Fits the same frozen pre-window model on the run-up to `month` in `ref_year` and
    compares the realised month against it. This is what lets the UI say "expected
    -1.2% (August seasonality), unexplained -7.0%" with a query id behind both halves
    rather than asserting the split in prose.
    """
    start = date(ref_year, month, 1)
    end = date(ref_year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    series, query_id = store.series(
        metric, cohort, start - timedelta(days=config.PRE_WINDOW_DAYS), end
    )
    # A KPI younger than ref_year has no prior August to compare against; evaluate()
    # returns None on the empty series and the caller reports 0.0% seasonality, which
    # is the honest answer rather than an extrapolated one.
    ev = evaluate(series, Window(start=start, end=end), agg=contracts.get(metric).agg)
    if ev is None:
        return 0.0, query_id
    return ev.delta_pct, query_id
