# Task 6 — Telemetry Panel: Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax. Every task is a full
> red→green→commit cycle. Do not write implementation before its test fails.

**Goal:** Put runtime cost on the page — stage latency, database work, model calls,
tokens, dollars — and turn the zero in the LLM column into an argument rather than an
absence.

**Architecture:** Stage timings are collected inside `pipeline.diagnose()` with
`time.perf_counter()` and travel on the payload. Query counts come from a counter on
`Store`, because only `Store` knows which calls were cache hits. `queries_on_card` is
patched in at the end of `narrate()` via `model_copy`, because counting it needs the
finished card. Narration recomputes nothing, as always.

**Tech stack:** Python 3.12, Pydantic v2 (frozen), DuckDB, Streamlit, pytest.

**Spec:** [`taskflow/taskflow.md`](taskflow.md) § "Task 6 — Telemetry panel".
Closes **two** Minimum Prototype Expectation rows:

- **Row 10** — *"Runtime telemetry covering latency, model calls, token usage and estimated cost"* ❌ → ✅
- **Row 9** — *"A clear breakdown of LLM versus non-LLM processing"* ⚠️ README-only → ✅ on the page

After this task, **ten of ten MPE rows close.**

## Global constraints

- **Every number a user reads comes from `Store.q()` and carries a `query_id`.**
  Telemetry is the one deliberate exception — latency is a fact about the *process*,
  not about the data — and the panel must **say so in as many words** rather than
  leaving a judge to notice the missing id. Same carve-out Task 4 granted `Redaction`.
- **Pydantic models are `frozen=True`.** Build new objects, never mutate.
- **`NarrationPayload` is a `@dataclass`.** New fields need `field(default_factory=...)`
  and must follow existing defaulted fields.
- **Narration computes nothing.** It copies telemetry through; it does not time itself
  into existence or recompute a count.
- Run tests: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q`
- **The suite count is asserted.** `tests/test_docs.py` compares `README.md` against
  `pytest --collect-only`, and **fires on every task that adds tests** — update the
  README number in the *same commit*, or every intermediate commit is red. Baseline
  today: **200**.

---

## Jargon

| Term | Meaning here |
|---|---|
| **Stage** | One phase of `diagnose()`: `detect`, `drill`, `symptoms`, `rank`, `seasonal` on the detection path; `measure`, `symptoms`, `rank`, `seasonal` on the manual-window path. |
| **Registered query** | One issued through `Store.q()`. Gets a `query_id`, is logged to `query_log`, is replayable. These are the numbers a reader can audit. |
| **Unregistered query** | A metadata round trip that carries no user-facing number — `dim_universe()`, `events()`, `max_date()`. Deliberately has no `query_id`. Still costs latency. |
| **`_q_cache`** | `Store`'s per-instance memo of `query_id → (df, query_id)`. A cache hit does no database work. This is why "queries" is three different numbers. |
| **Cold / warm** | Whether `_q_cache` is empty. Measured below: **2.6× difference** in wall time. |
| **`queries_executed`** | Registered queries that actually hit DuckDB (cache misses). The runtime-cost number. |
| **`queries_cached`** | Registered calls served from `_q_cache`. Work avoided. |
| **`queries_on_card`** | Distinct `query_id`s reachable from the finished card — `len(pipeline.card_query_ids(card))`. The **provenance** number, not the cost number. |
| **Counterfactual cost** | What the optional LLM narrator *would* cost, computed from `config.MODEL`'s real price. Stated so "$0.0000" doesn't read as dodging the question. |

---

## The measurement — taken before planning

Against the live store, `mrr_renewals` at `DEFAULT_AS_OF`:

### Query traffic for one diagnosis

| Count | Value | What it is |
|---|---|---|
| `q()` calls issued | **125** | registered query calls |
| …of which executed | **86** | actual DuckDB round trips |
| …of which cache hits | **39** | served from `_q_cache` |
| `dim_universe()` calls | **34** | unregistered metadata |
| `events()` calls | **1** | unregistered metadata |
| **distinct ids on the card** | **19** | what a reader can replay |

### Stage latency

| stage | cold (ms) | warm (ms) |
|---|---:|---:|
| detect | 72.6 | 33.6 |
| **drill** | **759.1** | **208.0** |
| symptoms | 14.1 | 4.5 |
| rank | 361.5 | 224.4 |
| seasonal | 15.3 | 5.5 |
| **total** | **1222.6** | **475.9** |

`drill` is **62% of cold wall time** — the honest headline for the panel, and a better
story than a flat total: it says *where* the money goes.

---

## Three corrections to the taskflow's draft

### Correction 1 — `queries = len(card_query_ids(card))` understates the work by ~6×

The draft defines the panel's `queries` field as the count of query ids on the card:
**19**. The engine executed **86** registered queries plus **35** unregistered metadata
round trips. Labelling 19 as "queries" in a panel headed *runtime telemetry* is not a
rounding error — it reports a sixth of the work, in the one place on the page whose
entire purpose is honest cost accounting. A judge who instruments the thing finds a
number that flatters us.

Both numbers are meaningful and they answer different questions:

- **19** — "how much of this can I audit?" (provenance)
- **86** — "what did this cost to produce?" (runtime)

Fix: report both, under names that cannot be confused. **Never ship a bare field called
`queries`.** See D2.

### Correction 2 — the five-stage set is only valid on the detection path

Draft test: `assert set(t.stage_ms) == {"detect", "drill", "symptoms", "rank", "seasonal"}`.

`diagnose()` has two branches. Passing `cohort`+`window` — which is how every
`sparse_history` KPI is diagnosed, and the only way `payment_success_rate` is reachable
in the UI — skips detection and drill entirely and calls `anomaly.measure()` instead.
On that path the stage set is `{"measure", "symptoms", "rank", "seasonal"}` and the
draft assertion fails. Fix: `stage_ms` reflects the path actually taken, and the test
asserts against the path. See D4.

### Correction 3 — timings are cache-dependent, and the test fixture is warm

Cold total 1223 ms; warm total 476 ms — **2.6×**. The `store` fixture in
`tests/conftest.py` is `scope="session"`, so `_q_cache` is warm by the time most tests
run, and *how* warm depends on test execution order. Any assertion on an absolute
duration or an absolute `queries_executed` is order-dependent and will flake.
**Assert structure and zero, never a duration** — which the taskflow says, and then its
own draft test half-violates. See D7.

---

## Decisions

**D1 — Telemetry is a process fact and carries no `query_id`. The panel says so.**
This is the second deliberate exception to "every number traces to a query" (Task 4's
`Redaction` was the first). Latency is not a fact about the data and there is no query
behind it. Leaving that unexplained invites the reading that we forgot; stating it makes
it a considered boundary. One sentence in the panel, permanently.

**D2 — Three query counts, each unambiguously named. No field called `queries`.**

```python
queries_executed: int    # registered queries that hit DuckDB
queries_cached: int      # registered calls served from Store._q_cache
queries_on_card: int     # distinct query_ids a reader can replay
```

Plus one honest caption: metadata lookups (`dim_universe`, `events`) are **not** counted,
because they carry no user-facing number and therefore no `query_id` — the same rule
that governs the rest of the system, applied consistently rather than conveniently.

**D3 — The counter lives on `Store`, not in `pipeline`.**
Only `Store.q` knows whether a call was a cache hit. Counting from outside means
re-deriving the `query_id` hash and duplicating cache logic — two implementations of one
truth, which drift. `Store` gains a plain counter dict; `diagnose()` snapshots it before
and after and reports the delta. Snapshot-and-subtract also means a shared, long-lived
`Store` (which is what Streamlit has) reports **per-diagnosis** numbers, not
since-boot totals.

**D4 — `stage_ms` keys reflect the path taken.**
Detection path: `detect`, `drill`, `symptoms`, `rank`, `seasonal`.
Manual-window path: `measure`, `symptoms`, `rank`, `seasonal`.
The panel renders whatever keys are present. Tests assert against the path, not a
hardcoded five. A dict whose keys describe what actually ran beats a dict padded with
`0.0` for stages that never executed — a zero would read as "instant", not "skipped".

**D5 — `total_ms` covers `diagnose()`; narration is its own stage.**
`total_ms` is wall time for the whole of `diagnose()`, so it is always **≥** the sum of
stages (the difference is focal selection and payload construction, both un-timed and
sub-millisecond). Narration is added as a `narrate` entry in `stage_ms` by `narrate()`
itself — it is a process fact about a process step, which is exactly what this field is
for, and leaving it out would make the panel's total quietly smaller than the wall clock
a user experiences.

**D6 — `queries_on_card` is patched in via `model_copy` at the end of `narrate()`.**
`card_query_ids()` needs the finished card, so the number cannot exist when `diagnose()`
builds the telemetry. It is set **once**, in `narrate()`, after the card is assembled —
covering both the cause and no-cause branches from one place. This is not narration
computing a number about the *data*; it is counting its own output.

**D7 — Assert structure and zero, never a duration.**
Tests assert: the stage keys match the path, `total_ms >= 0`, `total_ms` is within a
generous factor of the stage sum, `llm_calls == 0`, `llm_cost_usd == 0.0`, and
`queries_executed + queries_cached == queries_issued`. **No test asserts a millisecond
bound.** `test_pipeline.py::test_runs_within_the_latency_budget`'s existing 5.0 s bound
stays exactly as it is — do not tighten it to make telemetry look good.

**D8 — The counterfactual gets real arithmetic, not a hand-wave.**
The draft copy says "~1 call and ~2k tokens". A judge who knows the API will price it.
`config.MODEL` is `claude-sonnet-5` at **$2.00 / MTok input, $10.00 / MTok output**.
For one narration call carrying the evidence payload in and prose out:

| | tokens | rate | cost |
|---|---:|---:|---:|
| input (payload + system) | ~3,500 | $2.00/MTok | $0.0070 |
| output (card prose) | ~600 | $10.00/MTok | $0.0060 |
| **total per diagnosis** | | | **≈ $0.013** |

Stated as an estimate with its inputs shown, so it is checkable. The point lands harder
with a real number: *the narrator would cost about 1.3 cents and change no figure on
the page.*

**D9 — `telemetry` defaults to `None` on `DiagnosisCard`.**
Frozen Pydantic with a default keeps every existing construction site valid —
`DiagnosisCard.no_anomaly()` included, which has no pipeline behind it and legitimately
has no telemetry.

**D10 — The panel is an expander, placed after the Diagnosis section.**
Collapsed by default so it does not compete with the evidence, but above the final
caption where a judge scanning the bottom of the page will find it. It is the video's
closing beat, so it must not require scrolling past the fold to reach.

---

## File structure

| File | Change |
|---|---|
| `ledgerlens/models.py` | **Add** `Telemetry`; `DiagnosisCard.telemetry: Telemetry \| None = None`. |
| `ledgerlens/store.py` | **Add** `self.stats` counter; increment in `q()`; `stats_snapshot()`. |
| `ledgerlens/pipeline.py` | Time each stage; build `Telemetry`; put it on the payload. |
| `ledgerlens/narrate.py` | `NarrationPayload.telemetry`; carry to both card branches; set `queries_on_card` and the `narrate` stage. |
| `app.py` | The ⏱ expander: stage table, the zero-as-a-claim paragraph, the counterfactual. |
| `tests/test_telemetry.py` | **New.** |
| `README.md`, `CLAUDE.md`, `docs/telemetry_decisions.md` | Claims + decisions record. |

---

## Task 6.1 — `Telemetry` model and the `Store` counter

**Files:** Modify `ledgerlens/models.py`, `ledgerlens/store.py`. Test `tests/test_telemetry.py` (create).

**Interfaces produced:**
- `models.Telemetry(stage_ms, total_ms, queries_executed, queries_cached, queries_on_card, llm_calls, llm_tokens, llm_cost_usd)` — frozen.
- `models.DiagnosisCard.telemetry: Telemetry | None = None`
- `Store.stats: dict[str, int]` with keys `issued`, `executed`, `cached`
- `Store.stats_snapshot() -> dict[str, int]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_telemetry.py
"""Runtime telemetry: latency, database work, model calls, tokens, cost.

Closes MPE rows 9 and 10. The zero in the LLM column is the product's strongest
single claim, so it is asserted here rather than merely printed.

Every assertion in this file is about STRUCTURE or about ZERO. None is about a
duration: `Store._q_cache` makes a warm run 2.6x faster than a cold one, and the
session-scoped `store` fixture is warm in an order-dependent way. A millisecond
bound here would flake. See docs/telemetry_decisions.md D7.
"""

from __future__ import annotations

import config
from ledgerlens import narrate, personas, pipeline
from ledgerlens.models import DiagnosisCard, Telemetry
from ledgerlens.store import Store


def test_telemetry_defaults_to_none_on_a_card_with_no_pipeline_behind_it():
    card = DiagnosisCard.no_anomaly("mrr_renewals", pipeline.DEFAULT_AS_OF)
    assert card.telemetry is None


def test_telemetry_model_defaults_the_llm_columns_to_zero():
    t = Telemetry(
        stage_ms={"detect": 1.0},
        total_ms=1.0,
        queries_executed=1,
        queries_cached=0,
        queries_on_card=0,
    )
    assert (t.llm_calls, t.llm_tokens, t.llm_cost_usd) == (0, 0, 0.0)


def test_store_counts_executed_and_cached_separately(tmp_path):
    """The three query counts are three different numbers. A cache hit does no
    database work and must not be billed as if it did."""
    s = Store(tmp_path / "t.duckdb")
    s.init_schema()
    before = s.stats_snapshot()
    s.q("SELECT 1 AS a")
    s.q("SELECT 1 AS a")          # identical -> cache hit
    after = s.stats_snapshot()
    assert after["issued"] - before["issued"] == 2
    assert after["executed"] - before["executed"] == 1
    assert after["cached"] - before["cached"] == 1
    s.close()
```

- [ ] **Step 2: Run and watch it fail**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_telemetry.py -q`
Expected: `ImportError: cannot import name 'Telemetry' from 'ledgerlens.models'`

- [ ] **Step 3: Implement**

In `ledgerlens/models.py`, beside `Redaction`:

```python
class Telemetry(BaseModel):
    """What this diagnosis cost to produce.

    The one deliberate exception to "every number carries a query_id", alongside
    Redaction: latency is a fact about the PROCESS, not about the data, and there is
    no query behind it. The UI states that rather than leaving it to be noticed.

    Three query counts, because "queries" is three different numbers and conflating
    them flatters us by roughly 6x. `queries_on_card` answers "how much of this can I
    audit"; `queries_executed` answers "what did this cost". Metadata lookups
    (dim_universe, events) are counted in NEITHER -- they carry no user-facing number
    and therefore no query_id.
    """

    model_config = ConfigDict(frozen=True)
    stage_ms: dict[str, float]
    total_ms: float
    queries_executed: int
    queries_cached: int
    queries_on_card: int = 0
    llm_calls: int = 0
    llm_tokens: int = 0
    llm_cost_usd: float = 0.0
```

On `DiagnosisCard`, after `redactions`:

```python
    telemetry: Telemetry | None = None
```

In `ledgerlens/store.py`, in `__init__` after the caches:

```python
        # Per-instance counters. `q` is the only registered path to the database, so
        # this is the complete picture of registered work -- and deliberately does NOT
        # count dim_universe/events/max_date, which carry no user-facing number.
        # Snapshot-and-subtract gives per-diagnosis deltas from a long-lived Store.
        self.stats: dict[str, int] = {"issued": 0, "executed": 0, "cached": 0}
```

In `q()`, immediately after `query_id` is computed:

```python
        self.stats["issued"] += 1
        if query_id in self._q_cache:
            self.stats["cached"] += 1
            return self._q_cache[query_id]
        self.stats["executed"] += 1
```

(replacing the existing bare `if query_id in self._q_cache: return ...`)

And a method:

```python
    def stats_snapshot(self) -> dict[str, int]:
        """A copy, so a caller holding it across a diagnosis sees a delta rather than
        a live view that moves under them."""
        return dict(self.stats)
```

- [ ] **Step 4: Run and verify green**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_telemetry.py -q`
Expected: 3 passed.

- [ ] **Step 5: Full suite + README count**

```bash
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest --collect-only -q | tail -2
```
Update both `README.md` test-count claims to the collected number.

- [ ] **Step 6: Commit**

```bash
git add ledgerlens/models.py ledgerlens/store.py tests/test_telemetry.py README.md
git commit -m "feat(models): Telemetry, and the Store counter that makes its numbers true"
```

---

## Task 6.2 — Time the stages in `diagnose()`

**Files:** Modify `ledgerlens/pipeline.py`, `ledgerlens/narrate.py`. Test `tests/test_telemetry.py`.

**Interfaces consumed:** `models.Telemetry`, `Store.stats_snapshot` (6.1).
**Interfaces produced:** `narrate.NarrationPayload.telemetry: Telemetry | None`.

- [ ] **Step 1: Write the failing tests**

```python
DETECT_STAGES = {"detect", "drill", "symptoms", "rank", "seasonal"}
MANUAL_STAGES = {"measure", "symptoms", "rank", "seasonal"}


def test_telemetry_reports_every_stage_of_the_detection_path(store):
    payload = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    t = payload.telemetry
    assert set(t.stage_ms) == DETECT_STAGES
    assert all(v >= 0 for v in t.stage_ms.values())


def test_total_is_at_least_the_sum_of_its_stages(store):
    """Structure, not a bound: total covers focal selection and payload construction
    too. The 0.9 slack absorbs perf_counter granularity, nothing more."""
    t = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store).telemetry
    assert t.total_ms >= sum(t.stage_ms.values()) * 0.9


def test_the_manual_window_path_reports_the_stages_it_actually_ran(store):
    """The sparse-history path skips detection and drill entirely. A hardcoded
    five-stage assertion would fail here -- and padding the dict with 0.0 for stages
    that never ran would read as 'instant' rather than 'skipped'."""
    from ledgerlens.models import Window

    payload = pipeline.diagnose(
        "mrr_renewals",
        pipeline.DEFAULT_AS_OF,
        store=store,
        cohort={"region": ["DACH"], "payment_rail": ["sepa"]},
        window=Window(start=date(2026, 8, 4), end=date(2026, 8, 17)),
    )
    assert set(payload.telemetry.stage_ms) == MANUAL_STAGES


def test_query_counts_are_internally_consistent(store):
    """issued == executed + cached, always. Absolute values are NOT asserted: the
    session-scoped store fixture is warm in an order-dependent way."""
    t = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store).telemetry
    assert t.queries_executed + t.queries_cached > 0
```

> Add `from datetime import date` to the test module imports.

- [ ] **Step 2: Run and watch them fail**

Expected: `AttributeError: 'NarrationPayload' object has no attribute 'telemetry'`

- [ ] **Step 3: Implement**

In `narrate.py`, add to `NarrationPayload` after `redactions`:

```python
    telemetry: "Telemetry | None" = None
```

and import `Telemetry` from `ledgerlens.models`.

In `pipeline.py`, add `import time` and a small helper:

```python
class _Stopwatch:
    """Stage timings for one diagnosis.

    A tiny class rather than scattered perf_counter pairs, so the stage names live in
    one place and a branch that skips a stage simply never records it -- see
    docs/telemetry_decisions.md D4.
    """

    def __init__(self) -> None:
        self.stage_ms: dict[str, float] = {}
        self._t0 = time.perf_counter()

    def time(self, stage: str, fn):
        start = time.perf_counter()
        try:
            return fn()
        finally:
            self.stage_ms[stage] = (time.perf_counter() - start) * 1000

    @property
    def total_ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000
```

Rewrite `diagnose()`'s body to time each call, e.g.:

```python
    watch = _Stopwatch()
    stats_before = store.stats_snapshot()

    if cohort is not None and window is not None:
        ev, query_id = watch.time(
            "measure", lambda: anomaly.measure(store, metric, cohort, window)
        )
        ...
    else:
        root = watch.time("detect", lambda: anomaly.detect(store, metric, as_of))
        if root is None:
            return None
        nodes = watch.time(
            "drill", lambda: anomaly.drill(store, root, _visible_dims(metric, role))
        )

    focal = anomaly.focal(nodes)
    symptoms = watch.time("symptoms", lambda: symptoms_mod.cluster(store, focal.window))
    hyps = watch.time("rank", lambda: hypothesis.rank(store, focal, symptoms))
    ...
    seasonal_pct, seasonal_query_id = watch.time(
        "seasonal", lambda: anomaly.seasonal_estimate(store, metric, root.cohort)
    )

    stats_after = store.stats_snapshot()
    telemetry = Telemetry(
        stage_ms=watch.stage_ms,
        total_ms=watch.total_ms,
        queries_executed=stats_after["executed"] - stats_before["executed"],
        queries_cached=stats_after["cached"] - stats_before["cached"],
    )
```

and pass `telemetry=telemetry` into the returned `NarrationPayload`.

> **Early returns.** `diagnose()` returns `None` in two places before telemetry exists.
> That is correct — there is no diagnosis to bill for — and `run()` already turns that
> into `DiagnosisCard.no_anomaly()`, whose `telemetry` is `None` by D9.

- [ ] **Step 4: Run and verify green.** Expected: 7 passed.

- [ ] **Step 5: Full suite + README count.** `test_pipeline.py` must stay green.

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(pipeline): stage timings and per-diagnosis query accounting"
```

---

## Task 6.3 — Carry telemetry onto the card

**Files:** Modify `ledgerlens/narrate.py`. Test `tests/test_telemetry.py`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_card_carries_the_telemetry_the_payload_measured(store):
    card = pipeline.run("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    assert card.telemetry is not None
    assert set(card.telemetry.stage_ms) >= DETECT_STAGES


def test_narration_is_timed_as_its_own_stage(store):
    card = pipeline.run("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    assert "narrate" in card.telemetry.stage_ms


def test_queries_on_card_matches_the_provenance_audit(store):
    """The provenance number, and it must equal what the audit actually finds --
    otherwise the panel is claiming an auditability it cannot deliver."""
    card = pipeline.run("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    assert card.telemetry.queries_on_card == len(pipeline.card_query_ids(card))
    assert card.telemetry.queries_on_card > 10


def test_the_provenance_count_is_smaller_than_the_work_done(store):
    """The correction that motivated this design: 19 ids on the card against ~86
    registered queries executed cold. Reporting the former as 'queries' in a runtime
    panel understates the work by roughly 6x. Both numbers are real; they answer
    different questions and must never be merged into one field."""
    fresh = pipeline.get_store()
    card = pipeline.run("mrr_renewals", pipeline.DEFAULT_AS_OF, store=fresh)
    t = card.telemetry
    assert t.queries_on_card < t.queries_executed + t.queries_cached
    fresh.close()


def test_offline_path_makes_no_model_calls(store):
    """The claim the whole README rests on, asserted rather than stated."""
    card = pipeline.run("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    t = card.telemetry
    assert (t.llm_calls, t.llm_tokens, t.llm_cost_usd) == (0, 0, 0.0)
    assert card.generated_by == "template"


def test_every_persona_gets_the_same_zero(store):
    payload = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    for pid in ("analyst", "cfo", "oncall", "growth"):
        card = narrate.narrate(payload, persona=personas.get(pid))
        assert card.telemetry.llm_calls == 0
```

- [ ] **Step 2: Run and watch them fail.** Expected: `AttributeError`/`None` on `card.telemetry`.

- [ ] **Step 3: Implement**

In `narrate.narrate()`, wrap the branch and patch the two derived fields in one place:

```python
def narrate(payload, persona=None, no_confident_cause=None) -> DiagnosisCard:
    who = persona or personas.get(personas.DEFAULT_PERSONA_ID)
    abstain = payload.no_confident_cause if no_confident_cause is None else no_confident_cause

    start = time.perf_counter()
    card = _no_cause_card(payload, who) if (abstain or not payload.ranked) else _cause_card(payload, who)
    narrate_ms = (time.perf_counter() - start) * 1000

    if payload.telemetry is None:
        return card
    # Both fields need the FINISHED card: queries_on_card counts its ids, and the
    # narration timing is not knowable until narration is done. Set once, here,
    # covering both branches. This is narration counting its own output -- not
    # narration computing a number about the data.
    from ledgerlens import pipeline as _pipeline

    telemetry = payload.telemetry.model_copy(
        update={
            "queries_on_card": len(_pipeline.card_query_ids(card)),
            "stage_ms": {**payload.telemetry.stage_ms, "narrate": narrate_ms},
        }
    )
    return card.model_copy(update={"telemetry": telemetry})
```

Add `import time` to `narrate.py`, and `telemetry=payload.telemetry` to both
`DiagnosisCard(...)` constructions so the field is populated before the copy.

> **Import cycle.** `pipeline` imports `narrate` at module level, so `narrate` must
> import `pipeline` **inside the function**, not at the top. This mirrors the existing
> lazy `from ledgerlens import contracts` in `_is_rate()`.

- [ ] **Step 4: Run and verify green.** Expected: 13 passed.

- [ ] **Step 5: Full suite + README count.**

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(narrate): carry telemetry, count the card's own provenance"
```

---

## Task 6.4 — The panel

**Files:** Modify `app.py`. Test `tests/test_app.py`.

- [ ] **Step 1: Write the failing test**

```python
def test_telemetry_panel_states_the_zero_and_prices_the_alternative(truth):
    at = AppTest.from_file(APP_PATH, default_timeout=180).run()
    text = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert at.exception == []
    assert "0 LLM calls" in text
    assert "$0.0000" in text
    assert "claude-sonnet-5" in text        # the counterfactual is priced, not waved at
    assert "no query_id" in text            # D1: the carve-out is stated, not hidden
```

- [ ] **Step 2: Run and watch it fail.**

- [ ] **Step 3: Implement** — after the Diagnosis section, before the final divider:

```python
with st.expander("⏱ Telemetry — latency, database work, model calls, cost"):
    t = card.telemetry
    if t is None:
        st.caption("No diagnosis ran, so there is nothing to account for.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Wall time", f"{t.total_ms:,.0f} ms")
        c2.metric("Queries executed", t.queries_executed, delta=f"{t.queries_cached} cached")
        c3.metric("Replayable on this card", t.queries_on_card)
        c4.metric("LLM cost", f"${t.llm_cost_usd:.4f}", delta=f"{t.llm_calls} calls")

        st.markdown("**Where the time goes**")
        st.dataframe(
            pd.DataFrame(
                [
                    {"stage": k, "ms": round(v, 1), "share": f"{100 * v / max(t.total_ms, 1e-9):.0f}%"}
                    for k, v in sorted(t.stage_ms.items(), key=lambda kv: -kv[1])
                ]
            ),
            width="stretch",
            hide_index=True,
        )

        st.markdown(
            f"**This diagnosis: {t.llm_calls} LLM calls, {t.llm_tokens} tokens, "
            f"${t.llm_cost_usd:.4f}.** Every number on this page came from a logged "
            f"SQL query with a replayable `query_id`. The ranking path is "
            f"deterministic Python and SQL **by design, not by omission** — which is "
            f"why the full test suite and this entire demo run with "
            f"`ANTHROPIC_API_KEY` unset."
        )
        st.markdown(
            f"With the optional LLM narrator enabled, narration alone would add about "
            f"one call per diagnosis on `{config.MODEL}` — roughly 3.5k input and 600 "
            f"output tokens, about **$0.013** at $2.00/$10.00 per MTok. It would change "
            f"the prose and **none of the numbers**: narration reads figures off the "
            f"payload and computes nothing."
        )
        st.caption(
            "Telemetry carries **no query_id**, and that is deliberate: latency is a "
            "fact about the process, not about the data, so there is no query behind "
            "it to replay. It is one of exactly two such exceptions on this page — the "
            "other is the redaction notice. Counts cover *registered* queries; "
            "metadata lookups (`dim_universe`, `events`) carry no user-facing number "
            "and are excluded on the same rule."
        )
```

- [ ] **Step 4: Run and verify green.**

- [ ] **Step 5: Eyeball it** — `streamlit run app.py`. Confirm `drill` tops the table
      and the share column sums to roughly 100%.

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(ui): the telemetry panel, and the zero as an argument"
```

---

## Task 6.5 — Decisions doc and claims

**Files:** `docs/telemetry_decisions.md` (new), `README.md`, `CLAUDE.md`, `taskflow/taskflow.md`.

- [ ] **Step 1:** Write `docs/telemetry_decisions.md` — the measurement table, D1–D10,
      the three corrections, and what is deliberately not built (no cross-run
      aggregation, no percentile latency, no token counting against a live API).
- [ ] **Step 2:** README — an "LLM vs non-LLM" section with the measured stage table and
      the priced counterfactual. This is MPE row 9's evidence.
- [ ] **Step 3:** `CLAUDE.md` — task 6 done; note the two `query_id` carve-outs
      (telemetry, redaction) as a convention, since a third would need the same argument.
- [ ] **Step 4:** `taskflow.md` — mark rows 9 and 10 ✅, task 6 done. **Ten of ten.**
- [ ] **Step 5:** Full suite, final README count, commit.

---

## Risks

| Risk | Mitigation |
|---|---|
| **A test asserts a duration and flakes.** Cold/warm is 2.6×, fixture warmth is order-dependent. | D7. No millisecond bounds. The existing 5.0 s budget test is left alone. |
| **`queries_executed` is 0 in a warm test.** | Never assert absolute counts; `test_the_provenance_count_is_smaller_than_the_work_done` opens a `fresh` store for the one comparison that needs a cold cache. |
| **Import cycle** — `narrate` importing `pipeline`. | Import inside the function, as `_is_rate()` already does for `contracts`. |
| **`_Stopwatch.time` swallows exceptions.** | It uses `try/finally` and re-raises; the timing is recorded either way. Do not convert to `except`. |
| **Telemetry drifts from reality if a stage is added later.** | `stage_ms` is built from what ran, so a new untimed stage shows up as a gap between `total_ms` and the sum. `test_total_is_at_least_the_sum_of_its_stages` notices a *negative* gap; a large positive gap is a signal to time the new stage. |
| **The panel's cost claim goes stale** if `config.MODEL` changes. | The rate is written beside the model id in the copy, and `tests/test_docs.py` already pins `config.MODEL`. A model change is a deliberate act that should update both. |

---

## Open question

**Should `queries_executed` also count unregistered metadata round trips** (`dim_universe`
× 34, `events` × 1)? They are real latency but carry no `query_id`.

My recommendation: **no** — count them nowhere, name them in the caption. Counting them
in `queries_executed` would put unauditable work into a field a reader will assume is
auditable, which is the exact confusion Correction 1 exists to prevent. Naming them in
one sentence is honest without muddying the number. If you want them visible, the clean
answer is a fourth field (`metadata_queries`), not a fatter third one — say so and I'll
add it.

Nothing in this plan has been executed. Say the word and I'll start at Task 6.1.
