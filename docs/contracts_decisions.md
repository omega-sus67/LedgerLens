# `contracts.py` — decisions, jargon, and implementation, end to end

> **New to the project?** Read **[how_it_works.md](how_it_works.md)** first -- it
> assumes no background at all and teaches the vocabulary this page uses freely
> (cohort, grain, blast radius, lineage, `Store.q()`). This document explains
> *decisions*; that one explains the *system* those decisions are about.

Read this beside [`ledgerlens/contracts.py`](../ledgerlens/contracts.py). It explains
every model, every field, and — the reason it exists — **why each decision went the way
it did**, including the things the contract deliberately refuses to do.

Nothing here is aspirational. Every claim is enforced by a test in
[`tests/test_contracts.py`](../tests/test_contracts.py), named inline as we go.

---

## 1. What a KPI semantic contract is, and why it is code

The Round 2 checklist asks for a "KPI semantic contract: definitions, calculations,
drivers, thresholds, lineage, access restrictions." Most answers to that row are a
document — a wiki page describing what a metric means, which is true on the day it is
written and quietly false six months later.

Ours is **executable**. The same object is read by three consumers:

| Consumer | Reads | Where |
|---|---|---|
| the detector | `thresholds` | `anomaly.scan_for_onset()`, `anomaly.drill()` |
| the UI | definition, SQL, lineage, access | the 📜 Contract expander in `app.py` |
| the test suite | all of it | `tests/test_contracts.py` |

That single fact is what makes the contract meaningful rather than decorative: drift
between what the contract *says* and what the engine *does* becomes a failing test, not a
surprise on stage. A document cannot fail CI.

### Why Python and not YAML

The obvious shape for a metric registry is YAML — it is what dbt, Cube, and every metrics
layer use, and it is the right answer when non-engineers edit it. We chose Python for two
reasons.

**The one that matters:** a mistyped dimension raises at **import**, therefore in CI.
Write `grain_dims=["regoin"]` and the process refuses to start. The equivalent YAML typo
is a string that validates fine and produces an empty drill-down at demo time. Pydantic
field validators turn a class of demo-day failures into a class of CI failures, and that
trade is the whole argument. (`test_unknown_grain_dim_fails_at_construction`)

**The local one, stated honestly:** a ROS 2 install on the development machine poisons
`PYTHONPATH`, and `import yaml` fails unpredictably as a result — which is also why every
Python invocation in this repo is prefixed `env -u PYTHONPATH -u AMENT_PREFIX_PATH`. A
config format that cannot be loaded reliably is not a config format.

The cost is real and worth naming: a non-engineer cannot edit a KPI definition without
touching Python. At the scale of a metrics layer with hundreds of KPIs, that cost wins and
YAML-with-a-schema is correct. At two (soon three) KPIs it does not.

---

## 2. Jargon glossary

Terms the file assumes, with the concrete value from this repo beside each.

| Term | Meaning | Here |
|---|---|---|
| **grain** | the row identity of a table — what one row *is* | `daily × region × segment × payment_rail × product` |
| **refresh cadence** | how often a source *claims* to update | `daily batch, 02:00 UTC` |
| **freshness / lag** | the **measured** counterpart: how old the newest row actually is | `github` was 12 days stale at the as-of date |
| **lineage** | the chain source system → artifact → table | `github` → `data/events_deploys.json` → `change_event` |
| **SCD-2** | slowly-changing dimension, type 2: history kept as versioned rows with validity ranges rather than overwritten | why `pricing_db` declares `on change (SCD-2 diff)` — a price change is derived by diffing consecutive versions |
| **blast radius** | a change event's declared scope, as a cohort | a dimension the source does not constrain is **omitted**, which makes it unconstrained — it matches everything |
| **cohort** | conjunction across keys, disjunction within a key | `{"region": ["DACH"], "segment": ["Enterprise"]}` → `region IN ('DACH') AND segment IN ('Enterprise')` |
| **MAD** | median absolute deviation — spread measured with medians | robust to the outlier we are hunting; a mean/σ z-score is dragged toward the anomaly and hides it |
| **robust z** | residual ÷ scaled MAD | the focal cohort sits at z ≈ −40 |
| **warmup** | minimum history before a baseline is trustworthy | 120 days; below it detection declines rather than guesses |
| **fail-open / fail-closed** | what an unmatched rule defaults to — permit or deny | `AccessRule` is fail-**open**, see §5 |
| **dimension-level security** | governs which *cuts* a role may see | this is what we implement |
| **row-level security** | governs which *records* a role may see | deliberately out of scope, see §11 |

---

## 3. `LineageStep` — and why `kind` exists

```python
source_system: str      # "github"       -- joined against change_event.source
artifact: str           # "data/events_deploys.json"
table: str              # "change_event"
grain: str              # "one row per merged deploy"
refresh_cadence: str    # "event-time webhook (seconds)"
kind: str = "metric"    # "metric" | "context" | "symptom"
```

Five of these fields are description. `kind` is the one that does work.

It exists because **the freshness panel must say different things about different rows**:

- a stale **metric** feed *invalidates the number itself* — if `fact_metric` stops at last
  Tuesday, today's headline is wrong, full stop;
- a stale **context** feed does not touch the number at all — it means a candidate cause
  might be missing from the ledger, which degrades the diagnosis toward "I don't know"
  rather than toward a confident wrong answer;
- a stale **symptom** feed weakens corroboration only, because ticket clusters are shown
  as supporting evidence and are **deliberately never scored**.

`kind` also selects which SQL measures the step (§10). Collapsing these three into one
"data source" concept would force the UI to render one caveat for three genuinely
different failure modes.

### The cadences differ on purpose

`daily batch, 02:00 UTC` · `event-time webhook (seconds)` · `weekly planning export` ·
`on change (SCD-2 diff)` · `hourly incremental`.

That spread is the checklist's *"heterogeneous sources with different grains and refresh
cadences"*, demonstrated rather than asserted — and it is what makes the measured lag
table interesting instead of uniform:

| source | kind | declared | measured lag at as-of |
|---|---|---|---|
| `billing_db` | metric | daily batch, 02:00 UTC | **0 days** |
| `github` | context | event-time webhook | 12 days |
| `launchdarkly` | context | event-time webhook | 11 days |
| `calendar` | context | weekly planning export | 15 days |
| `pricing_db` | context | on change (SCD-2 diff) | 15 days |
| `zendesk` | symptom | hourly incremental | 1 day |

Read the second and third rows carefully, because they are the honest part: both declare
*seconds* and both measure in *days*. That is not a broken pipeline — it means no deploy
has happened in twelve days. A webhook feed's lag measures **event scarcity**, not
staleness, and conflating the two would be the panel lying. The `billing_db` row is the
one where lag genuinely means staleness, and it reads 0.

---

## 4. `Thresholds` — the invariant the engine rests on

The most important object in the file.

```python
mad_z: float            = config.MAD_Z_THRESHOLD        # 3.5
min_consecutive: int    = config.MIN_CONSECUTIVE_PERIODS # 2
min_abs_delta_pct: float = config.MIN_ABS_DELTA_PCT      # 3.0
warmup_days: int        = config.DETECT_WARMUP_DAYS      # 120
direction: str          = config.DIRECTION               # "drop"
```

**Every default is exactly the matching global constant.** That is not tidiness — it is
the property that made wiring contracts into `scan_for_onset()` and `drill()` a
behaviour-preserving refactor **by construction** rather than by testing. An unset field
*cannot* change detection, because an unset field resolves to the number the engine was
already using.

Once you rely on that, it has to be guarded, and until Task 1 nothing guarded it. It is
now `test_threshold_defaults_are_exactly_the_global_constants`, asserted field by field so
a failure names the constant that drifted. If someone "tidies" `mad_z` to a literal `3.5`
and later changes `config.MAD_Z_THRESHOLD`, detection changes silently on every metric at
once. That test is the tripwire.

A second test, `test_mrr_thresholds_are_the_tuned_acceptance_values`, pins the tuple
`(3.5, 2, 3.0, 120)` — the four numbers `test_pipeline.py`'s acceptance test is tuned to.
Changing one becomes a deliberate act that must edit that line first.

### What each field does

- **`mad_z` (3.5)** — how statistically extreme a day must be. Residual ÷ scaled MAD, not
  ÷ σ: median-based spread is not dragged upward by the very outlier being hunted.
- **`min_consecutive` (2)** — how many breaching days in a row constitute an onset. A
  single bad day is noise; two is a change.
- **`min_abs_delta_pct` (3.0)** — the **practical**-significance gate, required *in
  addition to* the statistical one. This is a `SPEC-GAP` and worth understanding: the
  August seasonal dip sits at z ≈ −2.0 against daily noise, so across 31 days
  `P(z < −3.5)` is roughly 7% per day — about a 15% chance of a spurious two-day flag,
  which would make the `as_of=2026-07-31 → None` acceptance test a coin flip. Requiring
  both makes it deterministic: the seasonal dip is −1.2% and can never reach −3%; the
  injected incident is −8.2% and always does.
- **`warmup_days` (120)** — history required before a pre-window baseline is trustworthy.
  Below it `scan_for_onset` returns `None` — it *declines* rather than guessing. Task 3
  turns that decline into a visible, explained UI state.

### `direction` is declared, not enforced

Stated plainly in the source: `scan_for_onset` **hardcodes the negative sign**. Setting
`direction="spike"` would change nothing.

v1 flags drops only because the generator's quarter-end multiplier (1.35×) would make a
bidirectional detector fire at every quarter close. The real fix is a calendar-regressor
baseline, not a threshold — so it is a v2 change, not a config change.

The decision worth defending is keeping the field anyway, labelled. A governance object
that quietly omits a limitation implies a guarantee the engine does not make. Documenting
the gap *inside* the contract is strictly stronger than hiding it, and it means the day
someone implements bidirectional detection, the field is already there and already
rendered.

---

## 5. `AccessRule` — scope, and the fail-open decision

```python
policy_id: str      # "fin.rail_detail"
role: str           # "growth"
hidden_dims: list[str]  # ["payment_rail"]
reason: str         # "Payment-rail revenue splits are finance-restricted; ..."
```

**Dimension-level only.** It governs which **cuts** a role sees — never which rows, never
which measures. `growth` cannot break revenue out *by payment rail*; `growth` still sees
total revenue, which includes every rail. Row-level security is a real production
requirement and is deliberately out of scope; §11 says so rather than implying coverage
we do not have.

### Fail-open, and why

A role with no matching rule is **unrestricted**
(`test_unknown_role_is_unrestricted`). That is a deliberate choice against the security
default, so it needs an argument.

The sensitive surface here is a *named subset of dimensions*, not the metric itself. Under
fail-closed, every role nobody has written a policy for sees **nothing** — a new analyst
role would open the page to a blank drill-down with no error, and the failure mode of a
BI tool that silently shows less than the truth is worse than one that shows a documented
amount too much. Fail-closed is correct when the protected thing is the data; fail-open is
correct when the protected thing is an enumerated slice of it.

The mitigation is that the exception is *visible*: `policy_id` and `reason` are non-empty
on every rule (`test_policy_carries_an_id_and_a_reason`), and Task 4 renders redaction as
an explicit notice — *"2 deeper slices redacted by policy `fin.rail_detail` — payment-rail
revenue splits are finance-restricted"* — rather than silently dropping rows. **Redaction
with provenance.** A row that vanishes without explanation is indistinguishable from a
bug.

One policy is seeded today: `fin.rail_detail`, hiding `payment_rail` from `growth`. It was
written for Task 4 to consume, and it has a pleasant property for the demo — the true
cause of the incident *is* a rail-specific failure, so the entitlement scenario shows a
role that structurally cannot see the answer.

---

## 6. `KpiContract` validators — the CI mechanism

Three validators, all doing the same job: converting a demo-day failure into an import-
time one.

- **`_known_dims`** — every `grain_dim` is a key of `config.DIMENSIONS`.
- **`_known_hidden_dims`** — same for every `AccessRule.hidden_dims`, with the failing
  `policy_id` in the message.
- **`_known_event_types`** — every `related_event_types` and `anticipated_event_types`
  entry is a member of `ChangeEvent`'s `event_type` `Literal`.

The third reads the allowed set **off the model** rather than retyping it:

```python
EVENT_TYPES: frozenset[str] = frozenset(
    get_args(ChangeEvent.model_fields["event_type"].annotation)
)
```

Retyping the list would create a second source of truth that can silently diverge from the
first — exactly the drift the whole module exists to prevent. `contracts.py` imports
`models.py`, and `models.py` imports nothing from the package, so there is no cycle; the
`Store` import for `freshness()`'s type hint is under `TYPE_CHECKING` for the same reason.

---

## 7. `hidden_dims_for` and `visible_drill_dims`

```python
def visible_drill_dims(self, role: str) -> list[str]:
    hidden = set(self.hidden_dims_for(role))
    return [d for d in config.DRILL_DIMS if d not in hidden]
```

Note it returns a **filtered ordered list**, not a set difference. The output is handed
straight to `anomaly.drill(store, root, dims)`, and drill order affects which dimension
wins at each level of the top-down search — so a reordered list would silently change
which cohort becomes focal, which changes the diagnosis. The ordering is
`config.DRILL_DIMS`'s, always. `test_visible_dims_preserve_drill_order` pins it.

`hidden_dims_for` unions across rules and returns sorted output, so multiple policies
targeting the same role compose rather than the last one winning.

---

## 8. `get()` vs `thresholds()` — the deliberate asymmetry

```python
def get(metric) -> KpiContract:   # strict:  raises KeyError
def thresholds(metric) -> Thresholds:  # lenient: falls back to defaults
```

This is the subtlest decision in the file and the one most likely to be "cleaned up" into
a single lookup by a future contributor. It should not be.

- **The UI must refuse** to present a KPI nobody has defined. Rendering an empty Contract
  box would claim governance we do not have. `app.py` calls `get()`, so an ungoverned KPI
  fails loudly.
- **The engine must not crash** because metadata is missing. Detection is the thing that
  finds problems; it degrades to the documented global behaviour instead of taking the
  page down. `anomaly.py` calls `thresholds()`.

The consequence is the point: **the UI is where a governance gap becomes visible.** An
ungoverned metric still gets detected, and the moment anyone looks at it the page says so.
Both halves are pinned — `test_get_refuses_an_ungoverned_kpi` and
`test_thresholds_degrades_to_defaults`.

---

## 9. `related_event_types` vs `anticipated_event_types`

```python
related_event_types: list[str]              # what the ledger can show us today
anticipated_event_types: list[str] = []     # known drivers with no connector
```

Originally one list, and it was wrong in an interesting way. `mrr_renewals` declared
`vendor_incident` and `policy_change` among its related types — both genuine top-tier
drivers of renewal revenue, and **neither has a connector**. The ledger only ever contains
`deploy`, `feature_flag`, `campaign`, `price_change`.

So the single list conflated two very different statements: *"we watch for this"* and
*"we know this matters and cannot see it."* Splitting them makes both testable in the
direction that matters:

- `test_related_event_types_are_present_in_the_ledger` — everything we claim to watch is
  actually arriving. If a connector stops emitting a type, that is a silent blind spot and
  this catches it. **This is the anti-drift guard against `gen_data.py`.**
- `test_anticipated_event_types_are_genuinely_absent` — the other direction, and the one
  that keeps the claim honest. Anything we say we cannot see must actually be unseeable; a
  type that starts arriving belongs in `related`, and leaving it in `anticipated` would
  understate the system.

The second list also earns its place in the UI. The expander renders it as *"we would also
weigh `vendor_incident`, `policy_change` — no source is connected for these, so they can
never appear as a candidate."* That is the same instinct as the abstention path: **naming
what you cannot observe is a stronger claim than a silent gap.** A system that lists its
blind spots is one you can calibrate trust in.

---

## 10. `freshness()` — declared versus measured

The contract *declares* `daily batch, 02:00 UTC`. `freshness()` reports what is actually
there. Declared beside measured, in one table, is the checklist's *"evidence: freshness …
lineage"* row.

```python
def freshness(store, metric, as_of) -> list[SourceFreshness]
```

One row per `LineageStep`, with SQL selected by `kind`:

| kind | query |
|---|---|
| `metric` | `SELECT max(date) FROM fact_metric WHERE metric_name = $metric AND date <= $as_of` |
| `context` | `SELECT max(ts_start) FROM change_event WHERE source = $source AND CAST(ts_start AS DATE) <= $as_of` |
| `symptom` | `SELECT max(created_at) FROM ticket WHERE CAST(created_at AS DATE) <= $as_of` |

### Three decisions inside that

**(a) It routes through `store.q()`, never `store.con.execute`.** `Store.q` is the only
sanctioned path to the database: it hashes SQL+params into a `query_id`, logs the SQL, the
params and a byte-stable result preview to `query_log`, and returns the id alongside the
data. Every number a user reads carries the query that produced it, and
`store.replay(qid)` re-runs it and diffs against the stored preview. Freshness is a number
a user reads, so it is not exempt. `test_freshness_numbers_are_replayable` asserts every
returned id both resolves and replays clean.

**(b) `store.max_date()` is deliberately not reused**, despite existing and looking like
exactly the right helper. It calls `con.execute` directly, so its result is unauditable —
and it takes no as-of bound, which is (c).

**(c) Freshness is measured relative to `as_of`, never the wall clock.** This is the trap
the feature was built around and the reason the bound appears in all three queries.

The demo is a time-travel replay pinned at `DEFAULT_AS_OF = 2026-08-17`. The generator
writes through `GEN_END = 2026-08-31` — **fourteen days past the as-of date**. An
unbounded `max(date)` therefore returns data *from the future* relative to the replay, and
the panel prints:

> billing_db — **−14 days stale**

Measuring against the real wall clock is worse still: on a laptop in 2029 it reads
"1181 days stale" during a live demo. `test_freshness_is_never_negative` is the regression
test, and it asserts both `lag_days >= 0` and `last_seen <= as_of`.

`last_seen` and `lag_days` are `None` — rendered as "—", never as a lag of zero — when a
source has no rows. Note `_as_date` checks `value != value` rather than `is None`: pandas
returns `NaT` for a `NULL max()` over a timestamp column, `NaT is not None`, and
subtracting it produces a garbage lag instead of an error.

---

## 11. What is deliberately not here

Naming the boundary is a credibility move, not an apology — the same instinct as the
README's honesty section.

- **Row-level security.** We govern dimensions, not records. A role that may see EMEA but
  not NA is a real requirement and we do not implement it.
- **Per-role measure masking.** Roles see all measures or none.
- **Contract versioning / effective-dating.** A contract is a snapshot of what the
  business agrees *today*. There is no "what did this KPI mean in March", which a real
  governance layer needs the moment a definition changes mid-year.
- **Bidirectional detection.** `direction` is declared, not enforced (§4).
- **Approval workflow.** No notion of who ratified a contract or when. `owner` is a
  string, not an identity.
- **A real catalog backend.** In production this registry is Collibra / DataHub / Unity
  Catalog, and `contracts.py` becomes a thin adapter over it. The models are shaped to
  make that swap plausible; nothing here pretends it has happened.

---

## 12. How to add a third KPI

Task 3 does exactly this, so the recipe is worth having:

1. Generate the series in `gen_data.py`. **Do not perturb the existing two** — the
   acceptance test in `test_pipeline.py` asserts the exact injected incident and the exact
   rejected decoy, and `SEED = 20260815` makes that reproducible only if the new metric is
   additive.
2. Add the name to `config.METRICS`.
3. Register a `KpiContract` in `CONTRACTS`. **Step 2 without step 3 fails
   `test_every_metric_is_governed`, and step 3 without step 2 fails it too** — the
   coverage test asserts set equality in both directions, so the two halves cannot drift
   apart. That is the point of writing it as `==` rather than `<=`.
4. Set `status="sparse_history"` if it has less than `warmup_days` of history, and give it
   its own `thresholds=Thresholds(min_abs_delta_pct=...)`. A rate metric bounded near 98%
   needs a completely different relative gate from a dollar sum — **this is the case
   per-KPI thresholds exist for**, and the first time the contract stops being a mirror of
   `config`.
5. Expect `test_every_contract_currently_uses_the_global_defaults` to fail. It is written
   to fail: it documents that today every contract matches the globals, and its failure is
   how we confirm the divergence was intentional. Delete or narrow it then.
6. Declare lineage with the right `kind`s, and split `related_event_types` from
   `anticipated_event_types` honestly — the ledger tests check both directions.
