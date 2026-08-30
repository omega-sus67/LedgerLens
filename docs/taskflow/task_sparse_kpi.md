# Task 3 — Third KPI with Sparse History: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `payment_success_rate` as a third KPI with deliberately short history, so detection **declines** and says why, and the manual-window path still produces a full, traceable card.

**Architecture:** The KPI is a **ratio**, which the fact table cannot store additively. Rather than a schema change, the contract declares `source_metrics` — the physical `metric_name` rows backing the KPI — and `agg="ratio"`. `Store.series()` then issues `SUM(successes)/SUM(attempts)`, a correctly weighted rate. Every consumer of the engine already funnels through `series()`, so the whole chain follows for free. Generation uses an **isolated RNG stream** so the existing two metrics are bit-identical.

**Tech Stack:** Python 3.12, DuckDB, pandas, numpy, scipy, pydantic v2 (frozen), Streamlit (`<1.63`), pytest.

**Spec:**
- `taskflow/taskflow.md` § "Task 3 — Third KPI with sparse history"
- `details/…round_2_detailed_problem_statements_final_1.pdf`, Problem Track 3
- Prior art: `taskflow/task_persona.md`, `docs/contracts_decisions.md`

---

## ⚠️ Read this before starting: the estimate in `taskflow.md` is wrong

`taskflow.md` budgets **3h** and describes the work as generator + config + contract +
UI. Reading the code, Task 3 as literally specified has three hidden dependencies that
roughly double it. **The submission is 2026-08-30 and tasks 4–7 are also non-negotiable
checklist rows**, so this needs a decision before a line is written.

**Hidden dependency 1 — the fact table is additive; a rate is not.**
`Store.series()` is `SELECT date, SUM(value) …` ([store.py:148](../../ledgerlens/store.py#L148)).
Summing a 98% success rate across 99 slices yields 9702%. Every number in the system
flows through this one function, so a ratio KPI cannot be bolted on beside it.

**Hidden dependency 2 — `evaluate()` sums across days.**
`actual = float(win.sum())` ([anomaly.py:117](../../ledgerlens/anomaly.py#L117)). Over a
14-day window a rate series sums to ~13.7, which is meaningless to display.
`delta_pct` survives (a ratio of equal-length sums equals a ratio of means), but
`actual`, `expected` and `delta_abs` do not.

**Hidden dependency 3 — narration formats everything as dollars.**
`_money()` is applied to `delta_abs` unconditionally, so a rate KPI renders
`-$0.02`. `KpiContract.unit` exists and is currently `"USD/day"` for both KPIs; it has
to start doing work.

### The decision

| | Scope | Cost | What you keep | What you lose |
|---|---|---|---|---|
| **A. Full ratio KPI (recommended)** | Tasks A–G below | **~4.5h** | `payment_success_rate` exactly as `taskflow.md` and the `Thresholds` docstring anticipate; a genuinely correct weighted rate; per-KPI `min_abs_delta_pct` demonstrated on a bounded metric; "different aggregation logic" — a named brief complexity | the time |
| **B. Additive third KPI** | Replace the KPI with `failed_payments`, a count | **~2h** | both checklist rows (3 KPIs + sparse history); zero changes to `store.py`, `anomaly.py`, `narrate.py` | the rate-threshold demonstration the repo was built to expect; "aggregation logic" as a talking point |

**Recommendation: A**, but only if tasks 4–7 are on track. If they are not, take B — a
missing checklist row is a zero, and B closes both rows it needs to. **This plan
implements A.** Task G notes exactly what to delete to fall back to B.

---

## Global Constraints

- **Test command:** `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q`
- **Baseline: 160 tests pass** (verified 2026-08-29, after Task 2).
- **Regenerate after every generator change:** `.venv/bin/python -m ledgerlens.gen_data`.
- **The existing two metrics must come out bit-identical.** `test_pipeline.py` asserts the exact injected incident and the exact rejected decoy. Task A's first step is a fingerprint that makes any perturbation a test failure rather than a surprise.
- **Every number still carries a `query_id`.** `Store.q()` remains the only path to the database — including the new ratio SQL.
- **No LLM anywhere.** Unchanged.
- **Pydantic models are frozen.** Use `.model_copy(update=…)`.
- **`config.py` holds global defaults; per-KPI behaviour belongs in `contracts.py`.** The new `min_abs_delta_pct` goes in the contract, never in `config`.

---

## Part 1 — What the brief asks for

| Where in the brief | Requirement | Closed by |
|---|---|---|
| Min. Prototype | "Three to five connected KPIs across two or three data sources with different grains or refresh cadences." | Third KPI, own lineage + cadence. Tasks A, C |
| Min. Prototype | "One sparse-history or newly launched KPI scenario." | 55 days of history vs `warmup_days=120`. Tasks A, D |
| Min. Prototype | "One low-confidence scenario in which the engine requests clarification or abstains." | Detection declines and says why. Tasks D, F |
| Complexities | "Sparse history for new products, categories or markets." | The scenario is a newly launched payments rail metric |
| Complexities | "Inconsistent KPI definitions, hierarchies, calendars, business rules and **aggregation logic**." | `agg="ratio"` vs `agg="sum"`, declared in the contract. Task B |
| Complexities | "Different source-system refresh cadences, grains, data quality levels and **historical coverage**." | Third lineage source, own cadence, 55-day coverage |

Six rows again, three of them Minimum Prototype Expectations.

---

## Part 2 — The three design decisions

### 2.1 RNG isolation — the generator must not move

`generate()` uses **one sequential RNG stream**:

```python
rng = np.random.default_rng(config.SEED)
raw      = _raw_panel(slices, dates, rng, ...)   # mrr_renewals
raw_logo = _raw_panel(slices, dates, rng, ...)   # new_logo_bookings
_write_tickets(out_dir, rng)                     # consumes the rest
```

Inserting a third `_raw_panel(…, rng, …)` anywhere before `_write_tickets` shifts every
subsequent draw. Tickets move, symptom clusters move, and
`test_symptom_spike_is_the_only_surviving_cluster` fails — or worse, passes while the
acceptance numbers drift inside their band.

**Decision: a dedicated stream.** `config.SEED_SPARSE = 20260816`, and
`rng_psr = np.random.default_rng(config.SEED_SPARSE)` used for nothing else. The
existing `rng` is never touched, so the existing panels are bit-identical by
construction rather than by luck. Task A Step 1 pins that with a fingerprint test.

### 2.2 Ratio modelling — `source_metrics`, not a schema column

Three options were considered:

- **A denominator column on `fact_metric`.** Correct, but touches `SCHEMA`, the
  `INSERT … SELECT` column list in `load_all`, and the parquet writer — the three places
  a cold-clone install would break.
- **Store the rate directly, `AVG` it.** No. An unweighted mean of per-slice rates is
  not the overall rate, and this project does not ship numbers it cannot defend.
- **Two additive physical metrics, divided at query time.** ✅

The KPI is backed by two ordinary additive rows already supported by the schema:
`payment_successes` and `payment_attempts`. The contract declares:

```python
source_metrics=["payment_successes", "payment_attempts"]
agg="ratio"
```

and `Store.series()` branches once:

```sql
SELECT date,
       SUM(CASE WHEN metric_name = $num THEN value ELSE 0 END)
       / NULLIF(SUM(CASE WHEN metric_name = $den THEN value ELSE 0 END), 0) AS value
FROM fact_metric
WHERE metric_name IN ($num, $den) AND date BETWEEN $start AND $end AND <cohort>
GROUP BY date ORDER BY date
```

That is a **correctly weighted** rate — big slices count more, exactly as they should —
with no schema change and no new file format.

**`source_metrics` is one concept with three call sites.** Every place that filters on
`metric_name` must consult it, and there are exactly three:

| Call site | Today | Needs |
|---|---|---|
| `Store.series` | `metric_name = $metric` | ratio SQL when `agg="ratio"` |
| `Store.cohort_rows` | `metric_name = $metric` | count rows of the **denominator** metric |
| `contracts.freshness` | `params["metric"] = metric` | the denominator metric |

Missing `cohort_rows` is the expensive one: it silently returns 0 for every cohort,
which drives `C` to 0.0 for every candidate, which quietly destroys the ranking on this
KPI while every test about the *other* KPIs stays green. Task B tests it directly.

### 2.3 Ratio KPIs are manual-window only — and that is a real limitation, not a dodge

`drill()` computes `contribution = ev.delta_abs / (node.actual - node.expected)`
([anomaly.py:307](../../ledgerlens/anomaly.py#L307)). Contribution analysis **assumes
additivity**: a parent's delta is the sum of its children's. A rate has no such
decomposition — a cohort's rate movement is a mix effect plus a within-slice effect,
and splitting those needs a method we do not have.

We are saved by the sparse history, not by design: `detect()` returns `None`
(55 days < `warmup_days=120`), and `pipeline.diagnose()`'s manual path sets
`nodes = [root]` without ever calling `drill()`. So `drill()` never sees a ratio.

**State this in the contract and the docs rather than letting it be a happy accident.**
If this KPI ever accumulated 120 days of history, detection would start firing and
`drill()` would produce contribution numbers that do not mean what they say. Task C adds
a validator that makes `agg="ratio"` + auto-detectable history a *loud* failure rather
than a silent wrong answer.

### 2.4 The history length must be 55 days, not 45

`taskflow.md` says "~45 days". That number does not work, and the failure is not
obvious:

- `fit_pre_window()` hard-requires `len(pre) >= 30` ([anomaly.py:73](../../ledgerlens/anomaly.py#L73)).
- The demo runs at `DEFAULT_AS_OF = 2026-08-17`, **not** at `GEN_END = 2026-08-31`.
- A 14-day manual window ending at `as_of` starts 2026-08-04. It needs ≥30 pre-window
  days before that, i.e. data from 2026-07-05 or earlier.
- 45 days back from `GEN_END` is 2026-07-18 → only **17** pre-window days at `as_of` →
  `fit_pre_window` returns `None` → `measure()` returns `None` → **the manual path fails
  too**, and the task delivers a KPI that can do nothing at all.

**Decision: launch 2026-06-23.** That is 55 days to `as_of` (41 pre-window days for the
demo window — comfortable margin) and 70 days to `GEN_END`. Both are far below
`warmup_days=120`, so detection still declines. `config.SPARSE_LAUNCH` carries the date
with this reasoning as a comment.

---

## Part 3 — File structure

| File | Status | Responsibility |
|---|---|---|
| `config.py` | Modify | `SEED_SPARSE`, `SPARSE_LAUNCH`, `PSR_*` generator constants. `METRICS` gains the KPI. |
| `ledgerlens/gen_data.py` | Modify | `_write_sparse_metric()` on an isolated RNG; appended to the parquet. |
| `ledgerlens/contracts.py` | Modify | `source_metrics` + `agg` on `KpiContract`; the `payment_success_rate` contract; the ratio/warmup validator. |
| `ledgerlens/store.py` | Modify | `series()` ratio branch; `cohort_rows()` denominator mapping. |
| `ledgerlens/anomaly.py` | Modify | `evaluate()` reports window **means** for ratio metrics. |
| `ledgerlens/narrate.py` | Modify | unit-aware `_format_value()`; sparse-history preamble on the card. |
| `app.py` | Modify | manual window controls for sparse KPIs; insufficient-history banner. |
| `tests/test_sparse_kpi.py` | **Create** | The whole scenario, end to end. |
| `tests/test_store.py`, `test_contracts.py`, `test_anomaly.py` | Modify | ratio aggregation units. |
| `docs/sparse_kpi_decisions.md` | **Create** | Task G. |

---

## Task A: Generate the KPI without moving anything else

**Files:**
- Modify: `config.py`, `ledgerlens/gen_data.py`
- Test: `tests/test_sparse_kpi.py` (create)

**Interfaces:**
- Produces: rows in `metrics.parquet` under `metric_name` in `{"payment_successes", "payment_attempts"}`, dates from `config.SPARSE_LAUNCH` to `config.GEN_END`, on the same `live_slices()` universe.

- [ ] **Step 1: Write the fingerprint test FIRST — before touching the generator**

This is the regression guard for the whole task. Capture it against the *current*
generator, then never let it change.

```python
# tests/test_sparse_kpi.py
"""The sparse-history KPI, end to end.

The first test in this file is the one that matters most: it asserts the two
pre-existing metrics are bit-identical after a third was added to the generator.
`gen_data.py` uses one sequential RNG stream, so an incautious insertion shifts every
downstream draw -- tickets, symptom clusters, and the acceptance numbers with them.
"""

from __future__ import annotations

import hashlib
from datetime import date

import pandas as pd
import pytest

import config
from ledgerlens import anomaly, contracts, narrate, personas, pipeline
from ledgerlens.models import Window

EXISTING = ["mrr_renewals", "new_logo_bookings"]


def _fingerprint(metric: str) -> str:
    df = pd.read_parquet(config.DATA_DIR / "metrics.parquet")
    df = df[df["metric_name"] == metric].sort_values(
        ["date", "region", "segment", "payment_rail", "product"]
    )
    payload = df["value"].round(6).to_numpy().tobytes()
    return hashlib.sha256(payload).hexdigest()[:16]


@pytest.mark.parametrize("metric", EXISTING)
def test_existing_metrics_are_bit_identical(truth, metric):
    """Pinned against the pre-task-3 generator. If this fails, the new metric is
    drawing from the shared RNG stream -- give it its own, do not update the hash."""
    expected = {
        "mrr_renewals": "REPLACE_ME_MRR",
        "new_logo_bookings": "REPLACE_ME_LOGO",
    }
    assert _fingerprint(metric) == expected[metric]
```

- [ ] **Step 2: Fill in the two real hashes, from the untouched generator**

```bash
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python - <<'PY'
import hashlib, pandas as pd, config
df = pd.read_parquet(config.DATA_DIR / "metrics.parquet")
for m in ("mrr_renewals", "new_logo_bookings"):
    d = df[df.metric_name == m].sort_values(["date","region","segment","payment_rail","product"])
    print(m, hashlib.sha256(d["value"].round(6).to_numpy().tobytes()).hexdigest()[:16])
PY
```

Paste both into the test. Run it — it must pass **before** any generator change.

- [ ] **Step 3: Add the config constants**

```python
# --- sparse-history KPI (task 3) -------------------------------------------
# Its own RNG stream. gen_data draws mrr_renewals, then new_logo_bookings, then
# tickets from ONE sequential generator, so a third draw on that stream shifts
# every subsequent value. An isolated stream makes the existing panels bit-identical
# by construction rather than by luck.
SEED_SPARSE = 20260816

# Launch date, chosen against DEFAULT_AS_OF (2026-08-17), NOT against GEN_END.
# fit_pre_window() requires >= 30 pre-window days. A 14-day manual window ending at
# as_of starts 2026-08-04, so the data must begin by 2026-07-05 for the MANUAL path
# to work at all. 2026-06-23 gives 55 days to as_of (41 pre-window days -- real
# margin) and 70 to GEN_END, both far below DETECT_WARMUP_DAYS = 120, so automatic
# detection still declines. "~45 days" does not work: it leaves 17 pre-window days
# and the manual path fails too.
SPARSE_LAUNCH = date(2026, 6, 23)

PSR_BASE_RATE = 0.982  # steady-state authorisation success
PSR_ATTEMPTS_PER_SLICE_DAY = 140.0  # scale for the denominator
PSR_NOISE_SD = 0.004  # day-to-day wobble in the rate
PSR_DIP_START = date(2026, 8, 3)  # same onset as the SEPA deploy
PSR_DIP_COHORT = {"region": ["DACH"], "payment_rail": ["sepa"]}
PSR_DIP_RATE = 0.913  # what the affected cohort falls to
```

Add to `METRICS`:

```python
METRICS = ["mrr_renewals", "new_logo_bookings", "payment_success_rate"]
```

- [ ] **Step 4: Write the generator function**

In `gen_data.py`, after `_write_metrics`:

```python
def _sparse_panels(slices, dates) -> tuple[np.ndarray, np.ndarray]:
    """payment_success_rate, stored as the two ADDITIVE metrics behind it.

    A rate cannot live in an additive fact table, so we store successes and attempts
    and let the contract divide them. See docs/sparse_kpi_decisions.md.

    Draws from its OWN RNG stream (config.SEED_SPARSE). Do not pass the shared `rng`
    here -- it would shift every downstream draw in generate().
    """
    rng = np.random.default_rng(config.SEED_SPARSE)
    n_s, n_d = len(slices), len(dates)

    attempts = rng.lognormal(
        math.log(config.PSR_ATTEMPTS_PER_SLICE_DAY), 0.25, size=(n_s, n_d)
    )
    attempts = np.round(attempts)

    rate = np.full((n_s, n_d), config.PSR_BASE_RATE)
    rate += rng.normal(0.0, config.PSR_NOISE_SD, size=(n_s, n_d))

    # The same SEPA connector release, seen through a different KPI. The dip is real
    # and material, but the metric is too young for the detector to be allowed to
    # find it -- which is the scenario this KPI exists to demonstrate.
    hit = np.array([_matches(s, config.PSR_DIP_COHORT) for s in slices])
    post = np.array([d >= config.PSR_DIP_START for d in dates])
    rate = np.where(hit[:, None] & post[None, :], config.PSR_DIP_RATE, rate)

    rate = np.clip(rate, 0.0, 1.0)
    successes = np.round(attempts * rate)
    return successes, attempts


def _write_sparse_metric(out_dir: Path, slices) -> None:
    """Append the sparse KPI's two physical metrics to metrics.parquet.

    Its date range is SHORTER than the other metrics' on purpose: history begins at
    config.SPARSE_LAUNCH, which is below DETECT_WARMUP_DAYS, so detect() declines.
    """
    dates = pd.date_range(config.SPARSE_LAUNCH, config.GEN_END, freq="D").date.tolist()
    successes, attempts = _sparse_panels(slices, dates)
    n_d = len(dates)

    frames = []
    for name, panel in (("payment_successes", successes), ("payment_attempts", attempts)):
        frames.append(
            pd.DataFrame(
                {
                    "date": np.tile(dates, len(slices)),
                    "metric_name": name,
                    "region": np.repeat([s[0] for s in slices], n_d),
                    "segment": np.repeat([s[1] for s in slices], n_d),
                    "payment_rail": np.repeat([s[2] for s in slices], n_d),
                    "product": np.repeat([s[3] for s in slices], n_d),
                    "value": panel.reshape(-1),
                }
            )
        )
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.date

    existing = pd.read_parquet(out_dir / "metrics.parquet")
    pd.concat([existing, df], ignore_index=True).to_parquet(
        out_dir / "metrics.parquet", index=False
    )
```

Call it in `generate()` on the line **after** `_write_metrics(...)`, and add to the
`truth` dict so ground truth stays measured rather than assumed:

```python
    _write_sparse_metric(out_dir, slices)
```

```python
        "sparse_metric": "payment_success_rate",
        "sparse_launch": config.SPARSE_LAUNCH.isoformat(),
        "sparse_days_generated": len(
            pd.date_range(config.SPARSE_LAUNCH, config.GEN_END, freq="D")
        ),
        "sparse_dip_cohort": config.PSR_DIP_COHORT,
        "sparse_dip_onset": config.PSR_DIP_START.isoformat(),
```

Record the *generated* span, not a span measured against `as_of`. Duplicating
`pipeline.DEFAULT_AS_OF` into `config.py` would create two constants that drift, and
`gen_data.py` must not import `pipeline` — the generator does not depend on the engine.
The as-of-relative figure is derived in the tests, where `pipeline` is already in scope.

- [ ] **Step 5: Regenerate and prove nothing moved**

```bash
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m ledgerlens.gen_data >/dev/null
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_sparse_kpi.py -q
```
Expected: both fingerprint tests **still pass**. If either fails, `_sparse_panels` is
drawing from the shared stream — fix the generator, never the hash.

- [ ] **Step 6: Add the coverage tests**

```python
def test_sparse_metric_has_short_history(truth):
    df = pd.read_parquet(config.DATA_DIR / "metrics.parquet")
    sparse = df[df["metric_name"] == "payment_attempts"]
    assert sparse["date"].min() == config.SPARSE_LAUNCH


def test_sparse_history_is_below_the_detection_warmup(truth):
    """The whole point: too young to auto-detect."""
    days = (pipeline.DEFAULT_AS_OF - config.SPARSE_LAUNCH).days + 1
    assert days < contracts.thresholds("payment_success_rate").warmup_days


def test_sparse_history_still_supports_a_manual_window(truth):
    """...but old enough that fit_pre_window's 30-day minimum is met, or the KPI
    could do nothing at all. This is why 45 days does not work."""
    from datetime import timedelta

    window_start = pipeline.DEFAULT_AS_OF - timedelta(days=13)
    pre_days = (window_start - config.SPARSE_LAUNCH).days
    assert pre_days >= 30, "manual path needs fit_pre_window's 30-day floor"
```

- [ ] **Step 7: Full suite, then commit**

```bash
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q
git add config.py ledgerlens/gen_data.py tests/test_sparse_kpi.py
git commit -m "feat(gen): sparse-history payment metrics on an isolated RNG stream"
```
Expected: `165 passed` (160 + 5). `test_contracts.py` may fail on `METRICS` having a
third entry with no contract — that is Task C; if it blocks, `xfail` it with
`reason="contract lands in Task C"` and clear the mark there.

---

## Task B: Teach `Store` about ratio KPIs

**Files:**
- Modify: `ledgerlens/store.py` (`series`, `cohort_rows`)
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `contracts.get(metric).source_metrics`, `.agg` (defined in Task C — see the note below).
- Produces: `Store.series("payment_success_rate", …)` returning a rate series in `[0, 1]`; `Store.cohort_rows` counting denominator rows.

> **Ordering note.** Task B needs the contract fields and Task C needs a working
> `series()` to test against. Break the cycle by adding **only** the two fields
> (`source_metrics`, `agg`) to `KpiContract` here, with defaults that leave the
> existing two KPIs untouched. The full `payment_success_rate` contract is Task C.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_store.py  (append)

def test_ratio_series_is_a_weighted_rate_not_a_sum(store):
    """SUM(value) across 99 slices would give ~97; a rate must stay in [0, 1].
    And it must be WEIGHTED -- an unweighted mean of per-slice rates is not the
    overall rate, and we do not ship numbers we cannot defend."""
    from datetime import date

    s, qid = store.series("payment_success_rate", {}, date(2026, 7, 10), date(2026, 7, 20))
    assert not s.empty
    assert s.dropna().between(0.0, 1.0).all()
    assert qid  # still a registered, replayable query

    num, _ = store.series("payment_successes", {}, date(2026, 7, 10), date(2026, 7, 20))
    den, _ = store.series("payment_attempts", {}, date(2026, 7, 10), date(2026, 7, 20))
    expected = (num / den).dropna()
    assert (s.dropna() - expected).abs().max() < 1e-12


def test_ratio_cohort_rows_counts_the_denominator(store):
    """cohort_rows filters on metric_name. Without the source_metrics mapping it
    returns 0 for a ratio KPI, which drives C to 0.0 for every candidate and
    silently destroys the ranking on this KPI alone."""
    from datetime import date

    from ledgerlens.models import Window

    w = Window(start=date(2026, 8, 4), end=date(2026, 8, 17))
    n, _ = store.cohort_rows({"region": ["DACH"]}, w, "payment_success_rate")
    assert n > 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_store.py -q`
Expected: FAIL — the series is empty, because no row has `metric_name = 'payment_success_rate'`.

- [ ] **Step 3: Add the two contract fields**

In `ledgerlens/contracts.py`, on `KpiContract`:

```python
    # The physical metric_name rows in fact_metric backing this KPI. Defaults to the
    # KPI's own name, so every existing contract is unchanged. A ratio KPI names its
    # numerator and denominator here instead -- see `agg`.
    source_metrics: list[str] = []
    # "sum"   -> SUM(value), the additive default.
    # "ratio" -> SUM(numerator)/SUM(denominator), a correctly weighted rate.
    agg: Literal["sum", "ratio"] = "sum"

    @model_validator(mode="before")
    @classmethod
    def _default_source_metrics(cls, data: dict) -> dict:
        """mode="before", because the model is frozen: a mode="after" validator would
        have to reach past the freeze with object.__setattr__ to fill a default."""
        if isinstance(data, dict) and not data.get("source_metrics"):
            data = {**data, "source_metrics": [data["name"]]}
        return data

    @model_validator(mode="after")
    def _ratio_needs_two_sources(self) -> "KpiContract":
        if self.agg == "ratio" and len(self.source_metrics) != 2:
            raise ValueError(
                f"{self.name}: agg='ratio' needs exactly two source_metrics "
                f"(numerator, denominator), got {self.source_metrics}"
            )
        return self
```

Add `Literal` and `model_validator` to the imports.

- [ ] **Step 4: Branch `series()` and `cohort_rows()`**

```python
    def series(
        self, metric: str, cohort: Cohort, start: date, end: date
    ) -> tuple[pd.Series, str]:
        """Daily series for a cohort, reindexed to a gapless daily range.

        Additive KPIs are SUM(value). Ratio KPIs are SUM(numerator)/SUM(denominator)
        -- a WEIGHTED rate, so a big slice counts more, which is what a rate means.
        An unweighted AVG across slices would be a different and wrong number.
        """
        from ledgerlens import contracts

        key = (metric, canonical_cohort_key(cohort), start.isoformat(), end.isoformat())
        if key in self._series_cache:
            return self._series_cache[key]

        contract = contracts.CONTRACTS.get(metric)
        if contract is not None and contract.agg == "ratio":
            num, den = contract.source_metrics
            sql = (
                "SELECT date, "
                "SUM(CASE WHEN metric_name = $num THEN value ELSE 0 END) "
                "/ NULLIF(SUM(CASE WHEN metric_name = $den THEN value ELSE 0 END), 0) "
                "AS value FROM fact_metric "
                "WHERE metric_name IN ($num, $den) AND date BETWEEN $start AND $end "
                f"AND {cohort_predicate(cohort)} GROUP BY date ORDER BY date"
            )
            params = {"num": num, "den": den, "start": start, "end": end}
        else:
            sql = (
                "SELECT date, SUM(value) AS value FROM fact_metric "
                f"WHERE metric_name = $metric AND date BETWEEN $start AND $end "
                f"AND {cohort_predicate(cohort)} GROUP BY date ORDER BY date"
            )
            params = {"metric": metric, "start": start, "end": end}

        df, query_id = self.q(sql, params, label=f"{metric} daily series")
        ...  # remainder unchanged
```

`cohort_rows` gets the same lookup, counting the **denominator**:

```python
        contract = contracts.CONTRACTS.get(metric)
        # A ratio KPI has no rows of its own name. Count the denominator: it is the
        # exposure base, which is what C's Jaccard is measuring anyway.
        physical = contract.source_metrics[-1] if contract is not None else metric
```

and bind `physical` where `metric` was bound.

- [ ] **Step 5: Run the tests**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_store.py -q`
Expected: PASS. The ratio tests need Task C's contract to exist — if `CONTRACTS` has no
`payment_success_rate` entry yet, add a minimal one now and enrich it in Task C rather
than leaving the tests red.

- [ ] **Step 6: Full suite, then commit**

```bash
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q
git add ledgerlens/store.py ledgerlens/contracts.py tests/test_store.py
git commit -m "feat(store): ratio-aware series() and cohort_rows() via contract source_metrics"
```

---

## Task C: The contract, its thresholds, and the ratio guard

**Files:**
- Modify: `ledgerlens/contracts.py`
- Test: `tests/test_contracts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_contracts.py  (append)

def test_every_metric_in_config_has_a_contract():
    """config.METRICS drives the UI selector. A metric without a contract renders a
    page with no thresholds, no lineage and no access policy."""
    for metric in config.METRICS:
        assert contracts.get(metric) is not None


def test_sparse_kpi_declares_its_own_practical_gate():
    """A rate bounded near 98% cannot move 3% without the business having ended.
    The global MIN_ABS_DELTA_PCT would make it undetectable in principle; per-KPI
    thresholds exist precisely for this."""
    th = contracts.thresholds("payment_success_rate")
    assert th.min_abs_delta_pct < config.MIN_ABS_DELTA_PCT


def test_sparse_kpi_is_marked_sparse():
    assert contracts.get("payment_success_rate").status == "sparse_history"


def test_sparse_kpi_declares_ratio_aggregation():
    c = contracts.get("payment_success_rate")
    assert c.agg == "ratio"
    assert c.source_metrics == ["payment_successes", "payment_attempts"]
    assert c.unit == "rate"


def test_ratio_kpi_may_not_be_auto_detectable():
    """drill() computes contribution as a share of the parent's delta, which assumes
    additivity. A rate has no such decomposition. Today this KPI is safe only because
    its history is too short to detect -- so make the coupling explicit: a ratio KPI
    whose warmup could be satisfied is a validation error, not a silent wrong answer."""
    import pytest

    from ledgerlens.contracts import KpiContract

    fields = contracts.get("payment_success_rate").model_dump()
    fields["status"] = "active"
    with pytest.raises(ValueError, match="ratio"):
        KpiContract(**fields)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_contracts.py -q`
Expected: FAIL — `unknown metric 'payment_success_rate'`.

- [ ] **Step 3: Add the contract**

```python
    "payment_success_rate": KpiContract(
        name="payment_success_rate",
        definition=(
            "Share of payment authorisation attempts that succeed, weighted by "
            "attempt volume. Launched 2026-06-23 with the new PSP integration."
        ),
        unit="rate",
        owner="payments platform",
        agg="ratio",
        source_metrics=["payment_successes", "payment_attempts"],
        status="sparse_history",
        calculation_sql=(
            "SELECT date, "
            "SUM(CASE WHEN metric_name = 'payment_successes' THEN value ELSE 0 END) "
            "/ NULLIF(SUM(CASE WHEN metric_name = 'payment_attempts' THEN value ELSE 0 END), 0) "
            "AS value FROM fact_metric "
            "WHERE metric_name IN ('payment_successes', 'payment_attempts') "
            "AND date BETWEEN $start AND $end GROUP BY date ORDER BY date"
        ),
        grain_dims=["region", "segment", "payment_rail", "product"],
        drivers=[
            "PSP or acquirer incidents",
            "connector releases on a specific rail",
            "card scheme or mandate rule changes",
            "issuer-side decline-rate shifts",
        ],
        related_event_types=["deploy", "feature_flag"],
        anticipated_event_types=["vendor_incident", "external"],
        lineage=[
            LineageStep(
                source_system="psp_webhook",
                artifact="authorisation events",
                table="fact_metric",
                grain="slice x day",
                refresh_cadence="every 15 minutes",
                kind="metric",
            ),
            LineageStep(
                source_system="github",
                artifact="deploy metadata",
                table="change_event",
                grain="event",
                refresh_cadence="on merge",
                kind="context",
            ),
        ],
        thresholds=Thresholds(
            # A rate that lives at 98.2% cannot fall 3% without the business having
            # ended. The global gate is calibrated for a dollar sum; this one is
            # calibrated for a bounded rate. This is the per-KPI divergence the
            # Thresholds docstring anticipated.
            min_abs_delta_pct=0.5,
            mad_z=3.0,
        ),
    ),
```

- [ ] **Step 4: Add the ratio/detectability validator**

```python
    @model_validator(mode="after")
    def _ratio_kpis_are_manual_only(self) -> "KpiContract":
        """drill() decomposes a parent delta into child contributions, which assumes
        additivity. A rate has no such decomposition -- a cohort's movement is a mix
        effect plus a within-slice effect, and separating them needs a method this
        build does not have.

        Today the sparse KPI is safe only because detect() declines on its short
        history and the manual path never calls drill(). That is an accident of the
        data, so pin it: a ratio KPI marked auto-detectable is a loud failure rather
        than a page of confident, wrong contribution numbers.
        """
        if self.agg == "ratio" and self.status != "sparse_history":
            raise ValueError(
                f"{self.name}: agg='ratio' requires status='sparse_history'. "
                "Contribution analysis in drill() assumes additivity, which a rate "
                "does not have; ratio KPIs are manual-window only in this build."
            )
        return self
```

- [ ] **Step 5: Run tests, full suite, commit**

```bash
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q
git add ledgerlens/contracts.py tests/test_contracts.py
git commit -m "feat(contracts): payment_success_rate contract, rate thresholds, ratio guard"
```

---

## Task D: Ratio-correct window measurement

**Files:**
- Modify: `ledgerlens/anomaly.py` (`evaluate`, `measure`)
- Test: `tests/test_anomaly.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_anomaly.py  (append)

def test_ratio_eval_reports_window_means_not_sums(store):
    """evaluate() sums across days. For a rate that gives ~13.7 over 14 days, which
    is meaningless on a card. delta_pct survives a sum/sum (equal day counts), but
    actual/expected/delta_abs must be per-day means."""
    from datetime import date

    from ledgerlens.models import Window

    w = Window(start=date(2026, 8, 4), end=date(2026, 8, 17))
    ev, _ = anomaly.measure(store, "payment_success_rate", {"region": ["DACH"]}, w)
    assert ev is not None
    assert 0.0 <= ev.actual <= 1.0
    assert 0.0 <= ev.expected <= 1.0
    # delta_abs is in rate POINTS, so it is small and negative for the dip cohort
    assert -1.0 < ev.delta_abs < 0.0


def test_sparse_kpi_declines_automatic_detection(store):
    """The scenario. 55 days of history against a 120-day warmup."""
    assert anomaly.detect(store, "payment_success_rate", pipeline.DEFAULT_AS_OF) is None
```

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL — `ev.actual` is ~13.7, not ~0.95.

- [ ] **Step 3: Make `evaluate` aggregation-aware**

`evaluate()` currently takes only a series. Give it an explicit mode rather than
having it guess:

```python
def evaluate(series: pd.Series, window: Window, agg: str = "sum") -> Eval | None:
    """Measure `window` against a model fitted on the PRE-window only.

    `agg="ratio"` changes only the REPORTED level, never the fit: a rate's window
    figure is the mean of its daily values, not their sum. delta_pct is identical
    either way -- a ratio of equal-length sums equals a ratio of their means -- so
    only actual, expected and delta_abs are affected.
    """
    ...
    actual = float(win.sum())
    expected = float(expected_daily.sum())
    if expected <= 0:
        return None
    ...
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
```

> Compute `delta_pct` from the **means** after the division, not before. The value is
> identical, but deriving both from the same pair keeps the object self-consistent for
> anyone reading it.

Thread the contract's `agg` through the three `evaluate()` call sites — `detect`,
`measure`, and `drill` — with `contracts.get(metric).agg`.

- [ ] **Step 4: Run, full suite, commit**

```bash
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q
git add ledgerlens/anomaly.py tests/test_anomaly.py
git commit -m "feat(anomaly): report window means for ratio KPIs, not day-sums"
```

---

## Task E: Unit-aware narration and the sparse-history preamble

**Files:**
- Modify: `ledgerlens/narrate.py`
- Test: `tests/test_sparse_kpi.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sparse_kpi.py  (append)

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
    assert sparse_card.causal_chain
    assert sparse_card.actions
    assert pipeline.card_query_ids(sparse_card)


def test_rate_kpi_is_never_formatted_as_dollars(sparse_card):
    """_money() on a rate renders '-$0.02'. The contract carries unit='rate'."""
    text = f"{sparse_card.headline} {sparse_card.summary}"
    text += " ".join(a.expected_impact for a in sparse_card.actions)
    assert "$" not in text


def test_card_states_the_history_limitation_up_front(sparse_card):
    """The decline must be legible. A blank success box is the failure mode."""
    assert "insufficient history" in sparse_card.summary.lower()
    assert "manual" in sparse_card.summary.lower()


def test_sparse_card_widens_its_own_uncertainty(sparse_card):
    """55 days of history is not 400. Actions grounded on it must say so."""
    assert any("history" in a.monitoring.lower() or "provisional" in a.expected_impact.lower()
               for a in sparse_card.actions)
```

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL on `$` present, and on the missing preamble.

- [ ] **Step 3: Add unit-aware formatting**

```python
def _format_value(metric: str, x: float) -> str:
    """Render a figure in its KPI's own unit. `_money` is not universal -- a rate
    formatted as dollars reads '-$0.02', which is both wrong and unreadable."""
    from ledgerlens import contracts

    contract = contracts.CONTRACTS.get(metric)
    if contract is not None and contract.unit == "rate":
        return f"{100 * x:.2f}%"
    return _money(x)


def _format_points(metric: str, x: float) -> str:
    """A DIFFERENCE in the KPI's unit. For a rate that is percentage points, which
    must not be confused with a percentage change."""
    from ledgerlens import contracts

    contract = contracts.CONTRACTS.get(metric)
    if contract is not None and contract.unit == "rate":
        return f"{100 * x:+.2f}pp"
    return _money(x)
```

Replace `_money(focal.delta_abs)` with `_format_points(payload.metric, focal.delta_abs)`
and `_money(focal.actual)` / `_money(focal.expected)` with `_format_value(...)`
throughout `_prose()` and `_actions()`.

Also add the helper the preamble in Step 4 needs:

```python
def _history_days(metric: str, as_of: date) -> int:
    """How much history this KPI actually has, for the sparse-history preamble.

    Read from config rather than counted from the data: the card states a fact about
    the KPI's launch, not about whatever window happens to be loaded.
    """
    from ledgerlens import contracts

    contract = contracts.CONTRACTS.get(metric)
    if contract is None or contract.status != "sparse_history":
        return 0
    return (as_of - config.SPARSE_LAUNCH).days + 1
```

`date` must be imported from `datetime` at the top of `narrate.py`.

- [ ] **Step 4: Add the sparse preamble**

At the top of `_cause_card`'s summary construction, for every persona:

```python
    contract = contracts.CONTRACTS.get(payload.metric)
    sparse_note = ""
    if contract is not None and contract.status == "sparse_history":
        sparse_note = (
            f"{payload.metric} has insufficient history for automatic detection "
            f"({_history_days(payload.metric, payload.focal.window.end)} days against a "
            f"{contracts.thresholds(payload.metric).warmup_days}-day warmup), so this "
            f"window was selected manually and the uncertainty here is wider than on "
            f"an established KPI. "
        )
```

Prepend `sparse_note` to every persona's summary in `_prose()`, and add to the P0
action's `monitoring`:

```python
        + (
            " Re-assess once this KPI has cleared its detection warmup; the current "
            "baseline rests on a short history."
            if contract is not None and contract.status == "sparse_history"
            else ""
        )
```

- [ ] **Step 5: Run, full suite, commit**

```bash
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q
git add ledgerlens/narrate.py tests/test_sparse_kpi.py
git commit -m "feat(narrate): unit-aware formatting and the sparse-history preamble"
```

---

## Task F: The manual-window UI

**Files:**
- Modify: `app.py`
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_app.py  (append)

def test_sparse_kpi_shows_the_insufficient_history_banner():
    """Selecting the sparse KPI must not render a blank success box."""
    at = AppTest.from_file(APP_PATH, default_timeout=180).run()
    at.sidebar.selectbox[0].set_value("payment_success_rate").run()
    assert at.exception == []
    text = " ".join([w.value for w in at.warning] + [m.value for m in at.markdown])
    assert "insufficient history" in text.lower()
    assert "manual" in text.lower()
```

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Add the manual-window branch**

```python
contract = contracts.get(metric)
manual_window = None
manual_cohort = None

if contract.status == "sparse_history":
    st.warning(
        f"**Insufficient history for automatic detection.** `{metric}` launched "
        f"{config.SPARSE_LAUNCH} — {(as_of - config.SPARSE_LAUNCH).days + 1} days of "
        f"history against a {contracts.thresholds(metric).warmup_days}-day warmup. "
        f"Detection is declined rather than run on a baseline that cannot support it. "
        f"Select a window manually below; uncertainty is wider than on an established KPI."
    )
    c1, c2 = st.columns(2)
    w_start = c1.date_input("Window start", date(2026, 8, 4), key="mw_start")
    w_end = c2.date_input("Window end", date(2026, 8, 17), key="mw_end")
    manual_window = Window(start=w_start, end=w_end)
    manual_cohort = {"region": ["DACH"], "payment_rail": ["sepa"]}
```

Thread `manual_cohort` / `manual_window` into `load_payload`, adding them to the cache
key as ISO strings (they change the payload, so unlike persona they **must** be in the
key — see `docs/persona_decisions.md` §10).

Gate the drill-down tree render on `contract.agg == "sum"`, with a caption saying why:

```python
    st.caption(
        "Drill-down is not shown for ratio KPIs: contribution analysis assumes a "
        "parent's delta is the sum of its children's, which a rate does not satisfy."
    )
```

- [ ] **Step 4: Run, full suite, commit**

```bash
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q
git add app.py tests/test_app.py
git commit -m "feat(ui): manual-window path and insufficient-history banner for sparse KPIs"
```

- [ ] **Step 5: Eyeball all three KPIs**

```bash
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m streamlit run app.py
```
Switch metric across all three and persona across all four (12 combinations). No
exceptions, no `$` on the rate KPI, no drill tree on the rate KPI, and the existing two
KPIs must look **exactly** as they did before Task 3.

---

## Task G: Document it

**Files:**
- Create: `docs/sparse_kpi_decisions.md`
- Modify: `README.md`, `taskflow/taskflow.md`, `CLAUDE.md`

- [ ] **Step 1: Write `docs/sparse_kpi_decisions.md`**

Companion to `contracts_decisions.md` and `persona_decisions.md`. Must cover:

1. Why the fact table cannot store a rate, and the three options weighed (§2.2 above).
2. Why the rate is **weighted**, and why an unweighted `AVG` would be a different and wrong number.
3. The RNG isolation decision and the fingerprint test that enforces it.
4. **Why 55 days and not 45** — the `fit_pre_window` 30-day floor against `DEFAULT_AS_OF`. This is the single most likely thing for a future editor to "simplify" back into a broken state.
5. Why ratio KPIs are manual-window only, that this is a **limitation and not a design choice**, and what it would take to lift (a rate decomposition separating mix from within-slice effects).
6. `evaluate`'s sum-vs-mean distinction, and why `delta_pct` is unaffected.
7. What abstention means here: the engine declines to *detect*, but still *explains* a window an analyst supplies. Declining to detect is not declining to help.

- [ ] **Step 2: README — extend the KPI section**

State plainly that LedgerLens now carries three KPIs across three source systems with
different cadences, that one of them is deliberately too young to auto-detect, and that
the system says so rather than rendering an empty result.

- [ ] **Step 3: Update `taskflow.md` and `CLAUDE.md`**

Mark Task 3 done. In `CLAUDE.md`, add to the conventions section: *"`gen_data.py` uses
one sequential RNG stream. Any new generated series MUST take its own
`default_rng(SEED_*)` or every downstream draw shifts. `tests/test_sparse_kpi.py`'s
fingerprint tests enforce this — if they fail, fix the generator, never the hash."*

- [ ] **Step 4: Full suite, then commit**

```bash
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q
git add docs/sparse_kpi_decisions.md README.md taskflow/taskflow.md CLAUDE.md
git commit -m "docs: sparse-history KPI decisions, ratio aggregation, RNG isolation"
```

### Falling back to Option B mid-task

If time runs out, the cut is clean because the tasks are ordered by dependency. Keep
Task A (rename the metric to `failed_payments`, drop `_sparse_panels`' rate logic for a
plain count, drop `payment_attempts`), keep Task C minus `agg`/`source_metrics`, keep
Tasks E–G minus the unit formatting. **Drop Tasks B and D entirely.** Both checklist
rows still close.

---

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| **The new metric perturbs the existing series.** | `test_pipeline.py` asserts the exact incident and the exact decoy. A shifted RNG could move numbers *within* their acceptance band — green tests, wrong demo. | Task A Step 1 writes the fingerprint test **before** any generator change, and Step 2 pins it against the untouched output. Never update the hash to make it pass. |
| **45 days is copied from `taskflow.md` without checking.** | `fit_pre_window` needs 30 pre-window days; 45 days leaves 17 at `as_of`, so the manual path fails too and the KPI can do nothing. | §2.4 shows the arithmetic; `test_sparse_history_still_supports_a_manual_window` asserts the floor directly. |
| **`cohort_rows` is forgotten.** | Returns 0 for the ratio KPI → `C` collapses to 0.0 for every candidate → the ranking on this KPI is silently wrong while every other test stays green. | `test_ratio_cohort_rows_counts_the_denominator` in Task B. |
| **`drill()` runs on a ratio.** | Contribution numbers that look authoritative and mean nothing. | Detection declines, so the manual path never drills — and Task C's validator makes the coupling explicit instead of accidental. |
| **The estimate.** | ~4.5h against a 2026-08-30 submission, with tasks 4–7 outstanding. | Option B is a real 2h fallback that closes both checklist rows. Decide before starting, not at hour three. |
| **Cache key.** | `load_payload` gains cohort/window, which change the payload. | Task F puts them in the key explicitly. Unlike persona, these cannot live below the cache boundary. |

## Estimate

| Task | Est. |
|---|---|
| A — generator + fingerprint guard | 1h |
| B — ratio-aware store | 1h |
| C — contract, thresholds, guard | 30m |
| D — ratio-correct evaluate | 45m |
| E — unit-aware narration | 45m |
| F — manual-window UI | 45m |
| G — docs | 45m |
| **Total** | **~5h** (Option B: ~2h) |
