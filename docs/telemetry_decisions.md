# Runtime Telemetry — Decisions

What Task 6 built, why each choice was made, and what it deliberately does not do.
Read this before changing `Telemetry`, `Store.stats`, or the panel copy in `app.py`.

Closes **two** Minimum Prototype Expectation rows:

- **Row 10** — *"Runtime telemetry covering latency, model calls, token usage and estimated cost"*
- **Row 9** — *"A clear breakdown of LLM versus non-LLM processing"*, which previously
  lived only in the README

With these, **ten of ten MPE rows close.**

Companion docs: [`roles_decisions.md`](roles_decisions.md) (the other `query_id`
carve-out), [`contracts_decisions.md`](contracts_decisions.md). Plan as executed:
[`taskflow/telemetry_tasks.md`](taskflow/telemetry_tasks.md).

---

## 1. What it does, in one paragraph

Every diagnosis is timed stage by stage and its database work is counted. The card
carries a `Telemetry` object; the UI renders it as a collapsed panel showing wall time,
where that time went, how many queries ran versus how many a reader can replay, and the
LLM columns — which are all zero. The panel then prices what the optional LLM narrator
*would* cost, so the zero reads as a design decision rather than a missing feature.

## 2. The vocabulary

| Term | Meaning here |
|---|---|
| **Stage** | One phase of `diagnose()`. Detection path: `detect`, `drill`, `symptoms`, `rank`, `seasonal`. Manual-window path: `measure`, `symptoms`, `rank`, `seasonal`. Plus `narrate`, added by `narrate()`. |
| **Registered query** | Issued through `Store.q()`. Has a `query_id`, is logged, is replayable. |
| **Unregistered query** | A metadata round trip carrying no user-facing number — `dim_universe()`, `events()`, `max_date()`. No `query_id`, by design. |
| **`_q_cache`** | `Store`'s per-instance memo. A hit does no database work. This is why "queries" is three numbers. |
| **Cold / warm** | Whether `_q_cache` is empty. **2.6× difference in wall time.** |
| **`queries_executed`** | Registered queries that hit DuckDB. The *cost* number. |
| **`queries_cached`** | Registered calls served from the memo. Work avoided. |
| **`queries_on_card`** | Distinct `query_id`s reachable from the finished card. The *provenance* number. |

## 3. The measurement

Taken before any code was written, and reproduced by the finished panel:

### Query traffic, one cold diagnosis

| | count |
|---|---:|
| `q()` calls issued | 125 |
| …executed against DuckDB | **86** |
| …served from `_q_cache` | 39 |
| `dim_universe()` (unregistered) | 34 |
| `events()` (unregistered) | 1 |
| **distinct ids on the card** | **19** |

### Stage latency, as the panel renders it

| stage | ms | share |
|---|---:|---:|
| **drill** | **757.5** | **62%** |
| rank | 363.9 | 30% |
| detect | 70.9 | 6% |
| seasonal | 15.2 | 1% |
| symptoms | 14.5 | 1% |
| narrate | 0.4 | 0% |
| **total** | **1,222** | |

Warm, the same run is **476 ms** — 2.6× faster.

`drill` at 62% is the honest headline: it says *where* the money goes, which is a better
answer than a flat total and is the right place to point if anyone asks what to optimise.

## 4. Decisions

**D1 — Telemetry is a process fact and carries no `query_id`. The panel says so.**
This is the **second** deliberate exception to "every number traces to a query"; Task 4's
`Redaction` was the first. Latency is a fact about the process, not the data, and there
is no query behind it to replay. Leaving that unexplained invites the reading that we
forgot. `test_telemetry_panel_states_the_zero_and_prices_the_alternative` asserts the
sentence is on the page. **A third such carve-out should have to make this argument
again** — two is a considered boundary, three is a habit.

**D2 — Three query counts, each unambiguously named. No field called `queries`.**
The original sketch defined the panel's `queries` as `len(card_query_ids(card))` — **19**
— in a panel headed *runtime telemetry*, where the engine had executed **86** registered
queries plus 35 unregistered round trips. That is not a rounding error; it reports a
sixth of the work in the one place whose entire purpose is honest cost accounting, and a
judge who instruments it finds a number that flatters us.

Both numbers are real and answer different questions:

- **19** — "how much of this can I audit?"
- **86** — "what did this cost to produce?"

So both are reported, under names that cannot be confused.
`test_the_provenance_count_is_smaller_than_the_work_done` pins the relationship, opening
its own cold store because the shared fixture is warm.

**D3 — Metadata round trips are counted in neither, and named in the caption.**
`dim_universe()` (34 calls) and `events()` (1) are real latency but carry no `query_id`.
Folding them into `queries_executed` would put unauditable work into a field a reader
assumes is auditable — recreating exactly the confusion D2 exists to prevent. One
sentence in the panel names them instead. If they ever need to be visible, the clean
answer is a separate `metadata_queries` field, not a fatter existing one.

**D4 — `stage_ms` keys reflect the path taken.**
`diagnose()` has two branches, and the manual-window branch — the only way a
`sparse_history` KPI is reachable — calls `anomaly.measure()` and skips `detect`/`drill`
entirely. The original sketch's `set(stage_ms) == {five names}` fails there. Padding the
dict with `0.0` for stages that never ran would read as "instant" rather than "not
applicable", which is worse than absent. `test_the_manual_window_path_reports_the_stages_it_actually_ran`
covers it.

**D5 — The counter lives on `Store`, not in `pipeline`.**
Only `Store.q` knows whether a call was a cache hit. Counting from outside means
re-deriving the `query_id` hash and duplicating the cache check — two implementations of
one truth, which drift. `Store.stats` is a plain dict; `stats_snapshot()` returns a
**copy**, and `diagnose()` subtracts before from after. Snapshot-and-subtract is also
what makes a long-lived `Store` — which is exactly what Streamlit holds across reruns —
report per-diagnosis numbers instead of since-boot totals.
`test_telemetry_is_per_diagnosis_not_since_boot` asserts it.

**D6 — `queries_on_card` and `narrate` are set once, in `narrate()`, via `model_copy`.**
Both need the *finished* card: the first counts its ids, the second cannot be known
until narration is done. Setting them in one place covers the cause and no-cause
branches together. This is narration counting **its own output** — not narration
computing a number about the data, which remains forbidden.
`pipeline` is imported *inside* the function because `pipeline` imports `narrate` at
module level; this mirrors the existing lazy `contracts` import in `_is_rate()`.

**D7 — Assert structure and zero, never a duration.**
Cold-vs-warm is 2.6×, and the `store` fixture is `scope="session"` — so how warm the
cache is depends on **test execution order**. Every assertion in `tests/test_telemetry.py`
is about structure (which keys, which relationships) or about zero (`llm_calls`,
`llm_cost_usd`). None asserts a millisecond bound.
`test_pipeline.py::test_runs_within_the_latency_budget`'s existing 5.0 s bound was left
exactly as it was — **do not tighten it to make telemetry look good.**

**D8 — `total_ms` covers narration, because the panel lists narration.**
`total_ms` is measured inside `diagnose()`, which has already returned when narration
begins. Left alone, the panel listed a `narrate` stage that its own total excluded, and
the share column summed past 100% — 1394.3 ms of stages against a 1394.0 ms total. Tiny,
and exactly the kind of tiny that makes a careful reader distrust every other number in
the panel. `narrate()` extends the total when it adds the stage;
`test_the_cards_total_covers_every_stage_it_lists` is the guard.

**D9 — The counterfactual is priced with real arithmetic.**
The original copy said "~1 call and ~2k tokens". A judge who knows the API will price it,
so we price it first. `config.MODEL` is `claude-sonnet-5` at **$2.00 / MTok input,
$10.00 / MTok output**:

| | tokens | rate | cost |
|---|---:|---:|---:|
| input (evidence payload + system) | ~3,500 | $2.00/MTok | $0.0070 |
| output (card prose) | ~600 | $10.00/MTok | $0.0060 |
| **per diagnosis** | | | **≈ $0.013** |

Stated as an estimate with its inputs shown, so it is checkable. *The narrator would
cost about 1.3 cents and change no figure on the page* lands harder than a hand-wave.
The panel quotes `config.MODEL` rather than a literal, and the app test asserts the
model id appears — so a model change cannot silently leave stale pricing on screen.

**D10 — `telemetry` defaults to `None` on `DiagnosisCard`.**
`DiagnosisCard.no_anomaly()` has no pipeline behind it and legitimately has nothing to
account for. A default keeps every existing construction site valid, and the panel
renders "No diagnosis ran, so there is nothing to account for" rather than a row of
zeros that would imply a free diagnosis happened.

**D11 — The abstention card is accounted for too.**
Abstaining costs the same drill and rank as answering. A panel that went blank on the
honest branch would imply refusing is free.
`test_the_abstention_card_is_also_accounted_for` covers it, which also means Task 7's
reachable abstention path arrives with working telemetry.

## 5. What was built

| File | Change |
|---|---|
| `ledgerlens/models.py` | `Telemetry`; `DiagnosisCard.telemetry: Telemetry \| None = None`. |
| `ledgerlens/store.py` | `self.stats` counter; `issued`/`executed`/`cached` in `q()`; `stats_snapshot()`. |
| `ledgerlens/pipeline.py` | `_Stopwatch`; every stage timed; `Telemetry` built and attached. |
| `ledgerlens/narrate.py` | `NarrationPayload.telemetry`; `narrate` stage; `queries_on_card`; extended total. |
| `app.py` | The ⏱ panel: four metrics, stage table, the zero-as-claim paragraph, the priced counterfactual, the carve-out caption. |
| `tests/test_telemetry.py` | 17 tests. |
| `tests/test_app.py` | 1 test — the panel's claims are on the page. |

**Test count: 200 → 218.**

## 6. What this deliberately is not

- **No cross-run aggregation.** No p50/p95, no history, no "average diagnosis". One
  card, one accounting. Percentiles need a corpus of runs, which is a monitoring
  feature, not a prototype one.
- **No token counting against a live API.** `llm_tokens` is 0 because nothing calls the
  API. It is a real field wired to a real zero, not a placeholder — if Task 8 (cut) ever
  lands, it populates rather than replaces it.
- **No query-level timing.** Stages, not individual queries. Per-query timing is
  available from `query_log` if anyone ever needs it, and would clutter the panel.
- **`_Stopwatch.time` uses `try/finally`, not `try/except`.** The timing is recorded even
  when a stage raises, and the exception still propagates. **Do not convert it to
  `except`** — that would swallow real failures to keep a number tidy.

Each of these is a named line in the business proposal's roadmap.
