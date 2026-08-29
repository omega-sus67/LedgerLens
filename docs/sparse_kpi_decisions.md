# The sparse-history KPI — decisions, jargon, and implementation, end to end

Third in the series, after [`contracts_decisions.md`](contracts_decisions.md) (task 1)
and [`persona_decisions.md`](persona_decisions.md) (task 2). This one covers
**`payment_success_rate`**: a third KPI that is deliberately too young to detect, and
the ratio-aggregation work it forced.

The plan is [`taskflow/task_sparse_kpi.md`](../taskflow/task_sparse_kpi.md). It records
the *reasoning*; this file records what shipped and where it differs.

**Status:** landed. **181 tests pass** (`160` before task 3, `+21`).

---

## 0. The one-sentence version

> **The engine declines to *detect* on a KPI too young to support a baseline, says so
> in as many words, and still *explains* a window an analyst supplies.**

Declining to detect is not declining to help. That distinction is the whole scenario.

---

## 1. What the Round 2 brief asked for

| Where in the brief | Requirement | Closed by |
|---|---|---|
| Min. Prototype | "Three to five connected KPIs across two or three data sources with different grains or refresh cadences." | Third KPI, own lineage (`psp_webhook`, every 15 minutes) |
| Min. Prototype | "One sparse-history or newly launched KPI scenario." | 56 days of history against a 120-day warmup |
| Min. Prototype | "One low-confidence scenario in which the engine requests clarification or abstains." | `detect()` returns `None`; the UI asks for a window |
| Complexities | "Sparse history for new products, categories or markets." | A newly launched payments-rail metric |
| Complexities | "Inconsistent KPI definitions, hierarchies, calendars, business rules and **aggregation logic**." | `agg="sum"` vs `agg="ratio"`, declared in the contract |
| Complexities | "Different source-system refresh cadences, grains, data quality levels and **historical coverage**." | A KPI whose date range is genuinely shorter than its siblings' |

---

## 2. Jargon glossary

| Term | Meaning here |
|---|---|
| **Sparse history** | A KPI with fewer days than `Thresholds.warmup_days`. `scan_for_onset` returns `None` before it looks at a single value. |
| **Ratio KPI** | `agg="ratio"`. Its value is `SUM(numerator)/SUM(denominator)`, not `SUM(value)`. |
| **`source_metrics`** | The physical `metric_name` rows in `fact_metric` backing a KPI. `["mrr_renewals"]` for an additive one; `["payment_successes", "payment_attempts"]` for the ratio. |
| **Manual path** | `pipeline.diagnose(cohort=…, window=…)`, which bypasses detection entirely. Pre-existing; task 3 gave it a UI. |
| **pp** | Percentage *points*. 98.2% → 91.3% is **−6.9pp** and **−7.0%**. Different numbers; the card never conflates them. |

---

## 3. Why a rate cannot simply be stored

`fact_metric` has one `value` column and `Store.series()` was `SELECT date, SUM(value)`.
Summing a 98% success rate across 99 slices returns ~97, for a quantity bounded at 1.
Three options were weighed:

| Option | Verdict |
|---|---|
| Add a `denominator` column to `fact_metric` | Correct, but touches `SCHEMA`, the `INSERT … SELECT` column list in `load_all`, and the parquet writer — the three places a cold-clone install breaks. Rejected as unnecessary risk. |
| Store the rate directly and `AVG` it across slices | **Rejected outright.** An unweighted mean of per-slice rates is not the overall rate. A slice with 4 attempts would count as much as one with 4,000. |
| **Two additive physical metrics, divided at query time** | ✅ Shipped. |

The KPI is backed by two ordinary rows the schema already supports. The contract
declares them, and `Store.series()` branches once:

```sql
SELECT date,
       SUM(CASE WHEN metric_name = $num THEN value ELSE 0 END)
       / NULLIF(SUM(CASE WHEN metric_name = $den THEN value ELSE 0 END), 0) AS value
FROM fact_metric
WHERE metric_name IN ($num, $den) AND date BETWEEN $start AND $end AND <cohort>
GROUP BY date ORDER BY date
```

That is a **weighted** rate: a big slice counts more, which is what a rate means. It
still goes through `Store.q()`, so it carries a `query_id` and replays like everything
else.

### `source_metrics` has exactly three call sites

Every place that filters on `metric_name` must consult it:

| Call site | What it needs |
|---|---|
| `Store.series` | the ratio SQL when `agg="ratio"` |
| `Store.cohort_rows` | count rows of the **denominator** |
| `contracts.freshness` | the denominator, for `kind="metric"` lineage steps |

**`cohort_rows` is the one that would have been missed.** A ratio KPI has no rows under
its own name, so without the mapping it returns 0 for every cohort — which drives `C`
to 0.0 for *every* candidate, silently destroying the ranking on this KPI while every
test about the other two stays green. `test_ratio_cohort_rows_counts_the_denominator`
exists for exactly that.

---

## 4. Why 55 days, and not the 45 the task list said

`taskflow.md` specified "~45 days". **That number does not work**, and the failure is
not obvious. This is the single most likely thing for a future editor to "simplify"
back into a broken state, so:

- `fit_pre_window()` hard-requires `len(pre) >= 30`.
- The demo runs at `DEFAULT_AS_OF = 2026-08-17`, **not** at `GEN_END = 2026-08-31`.
- A 14-day manual window ending at `as_of` starts 2026-08-04, so it needs data from
  2026-07-05 or earlier.
- 45 days back from `GEN_END` is 2026-07-18 → **17** pre-window days at `as_of` →
  `fit_pre_window` returns `None` → `measure()` returns `None` → **the manual path
  fails too**, and the KPI can do nothing at all.

`config.SPARSE_LAUNCH = date(2026, 6, 23)` gives 56 days at `as_of` (41 pre-window days
for the demo window) and 70 to `GEN_END` — both far below the 120-day warmup, so
detection still declines. `test_sparse_history_still_supports_a_manual_window` asserts
the 30-day floor directly, so shortening the history fails a test rather than a demo.

---

## 5. RNG isolation — the generator must not move

`generate()` draws from **one sequential stream**: renewals, then bookings, then
tickets. A third draw on that stream shifts every subsequent value — tickets move,
symptom clusters move, and the acceptance numbers drift *within* their band, which
means green tests and a wrong demo.

`_sparse_panels()` takes its own `np.random.default_rng(config.SEED_SPARSE)`. The
shared `rng` is never touched, so the existing panels are bit-identical **by
construction** rather than by luck.

`tests/test_sparse_kpi.py::test_existing_metrics_are_bit_identical` hashes both
pre-existing metrics against values pinned from the untouched generator.

> **If a fingerprint fails, fix the generator. Never update the hash.**

---

## 6. Ratio KPIs are manual-window only — a limitation, not a design choice

`drill()` computes `contribution = ev.delta_abs / (node.actual - node.expected)`.
Contribution analysis **assumes additivity**: a parent's delta is the sum of its
children's. A rate has no such decomposition — a cohort's movement is a *mix* effect
plus a *within-slice* effect, and separating them needs a method this build does not
have.

We are currently saved by the data, not by the design: `detect()` declines on the short
history, and the manual path sets `nodes = [root]` without ever calling `drill()`.

That is an accident, so it is pinned. The UI hides the drill tree for `agg="ratio"` and
says why, in the caption, on the page. If this KPI ever accumulated 120 days of history,
detection would start firing and `drill()` would produce contribution numbers that look
authoritative and mean nothing.

**Lifting this** requires a rate decomposition separating mix from within-slice effects.
It is named here rather than quietly permitted.

---

## 7. `evaluate()` — sums, means, and what is unaffected

`evaluate()` fits on the pre-window and then compares window totals:

```python
actual = float(win.sum())
expected = float(expected_daily.sum())
```

For a rate over 14 days that is ~13.7. `evaluate` gained `agg`, and for `"ratio"`
divides both by the day count to report **window means**.

`delta_pct` is **unaffected** — dividing `actual` and `expected` by the same `n` cannot
change their ratio — so only `actual`, `expected` and `delta_abs` move.
`test_ratio_delta_pct_is_unaffected_by_the_mean_conversion` pins that, so a future
editor cannot "fix" one without the other.

`delta_abs` for a rate is in **percentage points**, which is why narration needs three
formatters rather than one:

| Helper | Renders | Rate | Dollar |
|---|---|---|---|
| `_format_value` | a level | `91.29%` | `$416,144` |
| `_format_points` | a signed difference | `-6.88pp` | `-$416,144` |
| `_format_magnitude` | an unsigned difference, where the prose already carries direction | `6.88pp` | `$416,144` |

Writing `6.88%` where `6.88pp` is meant is the precise confusion this split prevents:
the rate fell 6.88 **points**, which is a 7.0 **percent** decline.

---

## 8. Two honesty fixes found by reading the generated card

Neither was in the plan. Both came from printing the card and looking at it.

**The P1 action talked about revenue on a KPI that does not measure revenue.** It read
*"Reclassifies +6.88pp from lost to at-risk in the current forecast"* — percentage
points cannot be reclassified in a revenue forecast. For a rate KPI the action is now
*"Flag DACH collections as at-risk … do not re-forecast on the assumption these
authorisations succeeded"*, and the impact declines to quantify:

> Not quantified in revenue terms: this KPI measures authorisation success, not
> collected revenue, and how much converts depends on retry recovery we do not model
> here.

**"Roughly 0.0% of that is August seasonality" was true and misleading.** The KPI
launched in June 2026 and has no prior August, so `seasonal_estimate` correctly returns
0.0. But 0.0 reads as *"we checked, the calendar is flat"* rather than *"we could not
check"*. The evidence step now says which one it is:

> No seasonal adjustment is applied: payment_success_rate launched 2026-06-23 and has
> no prior August to compare against, so the whole −7.0% is unexplained rather than
> partly calendar.

---

## 9. A latent bug the new KPI exposed

`Store.series()` returned a bare `pd.Series(dtype="float64")` when a query came back
empty — carrying a `RangeIndex`, not the gapless `DatetimeIndex` its own docstring
promises. Every caller that compares `series.index` to a `Timestamp` — including
`evaluate()`'s pre-window split — raised `TypeError` instead of returning `None`.

Unreachable for the established KPIs, which have rows on every date in range. The first
query for the sparse KPI's prior-August seasonality hit it immediately.
`test_empty_series_still_has_a_datetime_index` is the regression.

---

## 10. What the card actually says

```
payment_success_rate in DACH · sepa down 7% -- most consistent with deploy_sepa_v214

payment_success_rate has insufficient history for automatic detection (56 days
against a 120-day warmup), so this window was selected manually and the
uncertainty here is wider than on an established KPI. ...

  - payment_success_rate fell -7.0% against its deseasonalized baseline
      -> actual 91.29% vs expected 98.16%
  - No seasonal adjustment is applied: ... no prior August to compare against
      -> seasonal component 0.0%
  - Negative control: DACH · card|invoice should have been unaffected, and it was.
      -> +0.0%
  - Negative control: APAC|FR|Nordics|UK|US · sepa should have been unaffected.
      -> -0.1%
  - Support corroboration: 5 tickets keyed debit_payment_sepa in DACH · Enterprise
      -> 10x lift
```

The same SEPA connector release, found through a second KPI, with `C = 1.00` because
the deploy's declared blast radius (`DACH · sepa`) matches the analyst's cohort exactly.
Both negative controls pass. Score 0.83.

---

## 11. What is deliberately not here

- **No automatic detection on this KPI.** By design, and enforced by the warmup.
- **No rate decomposition.** See §6. Named, not silently permitted.
- **No revenue conversion.** We do not model how an authorisation failure converts into
  lost collections, so the P1 says so instead of inventing a multiplier.
- **No seasonality for this KPI.** No prior year, so none is claimed.
- **No bidirectional detection.** Unchanged from v1; `direction` is still declared, not
  enforced.

---

## 12. How to add a fourth KPI

1. Generate it in `gen_data.py` with **its own `default_rng(SEED_*)`**. Never draw from
   the shared stream.
2. Add it to `config.METRICS` and give it a `KpiContract`. If it is additive, that is
   all — `source_metrics` defaults to `[name]` and `agg` to `"sum"`.
3. If it is a ratio: set `agg="ratio"`, name numerator and denominator in
   `source_metrics`, set `unit="rate"`, and `status="sparse_history"` (see §6).
4. Update `test_fact_table_loaded`'s row arithmetic, which is expressed in terms of date
   ranges rather than a magic number.
5. Run the fingerprint tests. If they fail, the RNG is shared — go back to step 1.
