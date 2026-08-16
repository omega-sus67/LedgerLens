# LedgerLens — Implementation Specification

**Consumer:** Claude Code (agentic implementation).
**Product:** KPI root-cause engine for Accenture Innovation Challenge 2026, problem statement 3 (BusinessIntelligence.ai).
**Companion doc:** `businessintelligence-ai-redesign.md` (concept/architecture rationale). This file is the build contract.

---

## 0. Instructions to the implementing agent

**Read before writing code.**

1. **Build in the order given in §12.** Each phase has an acceptance test. Do not start phase N+1 until phase N's test passes. Run `pytest` after every phase.
2. **Determinism decides; the LLM investigates.** Any function that *decides* — flags anomalies, generates candidates from the ledger, scores, rejects via controls, estimates effects — must be pure Python/SQL. There are exactly **four** LLM call sites: `ledger/normalizer.py` (context extraction), `investigator.py::propose_tests` (template-gated extra checks), `investigator.py::unverified_causes` (causes outside connected data), `narrate.py` (narration). All four are **additive**: with `ANTHROPIC_API_KEY` unset, the pipeline must still produce a complete, correct `DiagnosisCard` and the full test suite must pass. Nothing an LLM emits may change the deterministic ranking or override a control result, and every LLM-derived element renders with a provenance label. If you want a fifth call site, stop and reconsider the design.
3. **Every number shown to a user must be traceable to a registered query.** See §6 (Query Registry). A computed value that cannot cite a `query_id` is a bug.
4. **Seed everything.** `SEED = 20260815` in config; pass it to every RNG. The demo must be byte-identical across runs.
5. **No new dependencies** beyond §2 without a written reason in the PR description. No Neo4j, no Qdrant, no LangGraph, no LangChain, no DoWhy, no cognee.
6. **Type hints everywhere**, `from __future__ import annotations`. Pydantic v2 for all cross-module data. Plain dataclasses are acceptable for module-internal structs.
7. **Write the test with the code**, not after. Ground truth is known (§4), so assertions are exact, not fuzzy.
8. If a spec detail is ambiguous, prefer the **simpler** implementation and add a `# SPEC-GAP:` comment explaining the choice. Do not invent extra features.

**Definition of done (Round 1):** `streamlit run app.py` opens on a laptop with no network except the Anthropic API, and a user can: see the flagged anomaly → see the attribution drill-down → see three ranked hypotheses where the true cause is #1 and the marketing decoy is explicitly rejected with the control that killed it → open any evidence bullet and see its SQL and result → click Confirm and see the prior update.

---

## 1. Repository layout

```
ledgerlens/
├── README.md
├── pyproject.toml
├── config.py                  # constants, paths, weights, thresholds, SEED
├── data/                      # generated artifacts (gitignored except .gitkeep)
│   ├── ledgerlens.duckdb
│   ├── metrics.parquet
│   ├── events_deploys.json
│   ├── events_flags.json
│   ├── events_campaigns.json
│   ├── events_pricing.json
│   ├── tickets.json
│   ├── slack.json
│   └── ground_truth.json      # written by generator; used ONLY by tests
├── ledgerlens/
│   ├── __init__.py
│   ├── models.py              # ALL Pydantic models (§3)
│   ├── store.py               # DuckDB lifecycle + query registry (§5, §6)
│   ├── gen_data.py            # synthetic data generator (§4)
│   ├── anomaly.py             # detection + hierarchical drill-down (§7)
│   ├── ledger/
│   │   ├── __init__.py
│   │   ├── connectors.py      # deterministic event ingestion (§8.1)
│   │   ├── normalizer.py      # LLM call site #1 (§8.2)
│   │   └── symptoms.py        # ticket clustering (§8.3)
│   ├── hypothesis.py          # candidates + 5-component scoring (§9)
│   ├── controls.py            # negative control generation + evaluation (§9.4)
│   ├── effect.py              # diff-in-diff + bootstrap CI (§10)
│   ├── ambiguity.py           # discriminating test (§11.1)
│   ├── learning.py            # Beta-Bernoulli priors (§11.2)
│   ├── narrate.py             # LLM call site #2 (§11.3)
│   └── pipeline.py            # end-to-end orchestration (§11.4)
├── app.py                     # Streamlit UI (§13)
└── tests/
    ├── test_gen_data.py
    ├── test_anomaly.py
    ├── test_ledger.py
    ├── test_hypothesis.py
    ├── test_controls.py
    ├── test_effect.py
    └── test_pipeline.py       # the acceptance test
```

---

## 2. Environment

Python 3.12. `pyproject.toml` dependencies, pinned to minor:

```
duckdb>=1.1
pandas>=2.2
pyarrow>=17
numpy>=2.0
scipy>=1.14
statsmodels>=0.14
pydantic>=2.9
streamlit>=1.39
anthropic>=0.40
plotly>=5.24          # treemap + timeline
pytest>=8.3
```

`ANTHROPIC_API_KEY` from env. **The pipeline must run end-to-end with the key absent** — both LLM call sites degrade gracefully (`normalizer` falls back to regex extraction, `narrate` falls back to a Jinja-style template renderer over the same `DiagnosisCard`). Tests run without a key.

### config.py

```python
SEED = 20260815
DB_PATH = Path("data/ledgerlens.duckdb")

# anomaly
MAD_Z_THRESHOLD = 3.5          # robust z on rolling-median residual
MIN_CONSECUTIVE_PERIODS = 2
CONTRIBUTION_FLOOR = 0.15      # child must explain >=15% of parent delta to recurse
MAX_DRILL_DEPTH = 3
STL_MIN_CYCLES = 2             # else fall back to rolling median

# hypothesis
LOOKBACK_DAYS = 21             # candidate window before anomaly onset
SCORE_WEIGHTS = {"T": 0.25, "C": 0.30, "D": 0.15, "N": 0.25, "P": 0.05}
SCORE_FLOOR = 0.45             # below this, emit "no candidate explains this"
AMBIGUITY_EPSILON = 0.08       # |s1 - s2| < eps -> discriminating test

# effect
BOOTSTRAP_ITERS = 2000
CI_LEVEL = 0.95

DIRECTION = "drop"             # v1 flags negative anomalies only (see §7.1 pitfall note)
MIN_SLICE_ROWS_PER_DAY = 3     # slices thinner than this are never tested (variance floor)
CONTRIB_DENOM_FLOOR = 0.02     # skip contribution recursion when |parent delta| < 2% of parent expected
LLM_TEST_BUDGET = 6            # max investigator-proposed tests per diagnosis
EXPLORER_QUERY_BUDGET = 12     # max exploratory queries when SCORE_FLOOR unmet

MODEL = "claude-sonnet-4-6"
```

Weights are displayed in the UI. They are a product decision, not a hidden hyperparameter.

---

## 3. Data contracts — `ledgerlens/models.py`

All models `pydantic.BaseModel` with `model_config = ConfigDict(frozen=True)` unless noted.

```python
Cohort = dict[str, list[str]]
# e.g. {"region": ["DACH"], "segment": ["Enterprise"], "payment_rail": ["sepa"]}
# Semantics: conjunction across keys, disjunction within a key.
# Absent key == unconstrained (matches all values of that dimension).
```

Cohort algebra lives in `models.py` as free functions and is used everywhere — implement carefully, it is the spine of the system:

```python
def cohort_predicate(c: Cohort) -> str: ...
    # -> "region IN ('DACH') AND segment IN ('Enterprise')"  (empty cohort -> "TRUE")

def cohort_intersect(a: Cohort, b: Cohort) -> Cohort | None: ...
    # per-key set intersection; returns None if any shared key intersects to empty

def cohort_complement(base: Cohort, dim: str, universe: list[str]) -> Cohort: ...
    # same as base but `dim` flipped to (universe - base[dim]); used by controls

def cohort_rows(con, c: Cohort, window: Window, metric: str) -> int: ...
    # row count in fact_metric for THE METRIC UNDER INVESTIGATION matching cohort+window.
    # PITFALL: without the metric filter, a blast radius unconstrained on metric
    # (e.g. the campaign) gets its |B| inflated by new_logo_bookings rows and the
    # Jaccard comparison silently breaks. Always pin the metric.
```

### Core models

```python
class Window(BaseModel):
    start: date
    end: date

class Anomaly(BaseModel):
    anomaly_id: str            # deterministic hash of metric+cohort+window
    metric: str
    cohort: Cohort
    window: Window
    onset: date                # first period breaching threshold
    actual: float
    expected: float            # deseasonalized baseline
    delta_abs: float
    delta_pct: float
    residual_z: float
    contribution: float        # share of PARENT delta explained; 1.0 at root
    depth: int
    parent_id: str | None
    query_id: str              # provenance for actual/expected

class ChangeEvent(BaseModel):
    event_id: str
    event_type: Literal["deploy","feature_flag","price_change","campaign",
                        "policy_change","vendor_incident","external"]
    ts_start: datetime
    ts_end: datetime | None
    source: str                # "github" | "launchdarkly" | "pricing_db" | "slack" | "zendesk" | "calendar"
    blast_radius: Cohort
    description: str
    evidence_refs: list[str]   # urls / ids
    extraction: Literal["deterministic","llm"] = "deterministic"
    confidence: float = 1.0    # <1.0 only for llm-extracted events

class SymptomCluster(BaseModel):
    cluster_id: str
    key: str                   # normalized error code or issue key, e.g. "ERR_SEPA_504"
    cohort: Cohort             # inferred from ticket account -> dims
    first_seen: date
    volume: int
    baseline_volume: float     # trailing 28d mean for the same key+cohort
    lift: float                # volume / max(baseline, 0.5)
    sample_refs: list[str]

class ControlResult(BaseModel):
    name: str                  # "DACH Enterprise card-rail renewals"
    cohort: Cohort
    prediction: Literal["should_be_flat","should_also_drop"]
    observed_delta_pct: float
    passed: bool
    query_id: str

class ComponentScores(BaseModel):
    T: float; C: float; D: float; N: float; P: float
    def total(self, w: dict[str, float]) -> float: ...

class Hypothesis(BaseModel):
    hypothesis_id: str
    anomaly_id: str
    event: ChangeEvent
    scores: ComponentScores
    total: float
    controls: list[ControlResult]
    symptoms: list[SymptomCluster]
    effect: EffectEstimate | None
    rejection_reason: str | None   # set when a control decisively fails
    query_ids: list[str]

class EffectEstimate(BaseModel):
    method: Literal["did_ratio","did_regression"]
    counterfactual: float
    actual: float
    impact_abs: float
    ci_low: float
    ci_high: float
    control_cohort: Cohort
    pre_fit_quality: float     # R^2 of pre-period fit — reported as FIT quality, never as causal evidence
    query_id: str

class DiscriminatingTest(BaseModel):
    h1_id: str; h2_id: str
    disagreement: str
    resolvable_now: bool
    sql: str | None            # populated when resolvable_now
    result: str | None
    proposed_experiment: str | None
    owner_hint: str

class ProposedTest(BaseModel):
    template: Literal["compare_cohort","check_metric_in_cohort",
                      "check_symptom_lift","check_temporal_order"]
    params: dict[str, str | list[str]]   # validated against dim_registry + metric list BEFORE execution
    rationale: str                        # LLM's one-line reason for the check
    result: ControlResult | None          # filled by the deterministic executor, never by the LLM
    provenance: Literal["llm"] = "llm"

class UnverifiedHypothesis(BaseModel):
    description: str
    needed_source: str                    # e.g. "competitor pricing feed", "CRM exit surveys"
    would_test: str                       # the check we'd run if that source were connected

class EvidenceStep(BaseModel):
    claim: str
    query_id: str
    observed: str

class Action(BaseModel):
    priority: Literal["P0","P1","P2"]
    owner: str
    action: str
    basis: str                 # what number justifies it, with query_id

class DiagnosisCard(BaseModel):
    headline: str
    summary: str
    causal_chain: list[EvidenceStep]
    effect: EffectEstimate | None
    ranked: list[Hypothesis]
    rejected: list[Hypothesis]
    open_question: DiscriminatingTest | None
    actions: list[Action]
    proposed_tests: list[ProposedTest]          # investigator lane; empty without API key
    unverified: list[UnverifiedHypothesis]      # investigator lane; empty without API key
    generated_by: Literal["llm","template"]
```

**Rule:** `narrate.py` may fill `headline`, `summary`, `claim` strings, and `Action.action` prose. It may **not** produce any numeric field. All numerics are copied from upstream objects by `pipeline.py` before the LLM is called.

---

## 4. Synthetic data generator — `gen_data.py`

Deterministic under `SEED`. Writes all files in `data/` plus `ground_truth.json`.

### 4.1 Dimensions and grain

Grain: one row per `(date, region, segment, payment_rail, product)`.

```
region:       DACH, UK, FR, US, APAC, Nordics
segment:      Enterprise, Mid, SMB
payment_rail: sepa, card, invoice
product:      A, B, C
dates:        2025-03-01 .. 2026-08-31   (549 days)
```

Full cross-product = 162 slices/day. Suppress implausible combos to keep it realistic: `sepa` only for `region in (DACH, FR, Nordics)`; `invoice` only for `Enterprise`. Roughly ~90 live slices.

### 4.2 Metrics

Two metrics in `fact_metric` (long format, `metric_name` column):

- `mrr_renewals` — the headline metric.
- `new_logo_bookings` — needed for the marketing decoy's negative control.

Generation for each slice, per day *t*:

```
base       = slice_base[slice]                     # drawn once, lognormal, seeded
trend      = 1 + 0.00035 * t
weekly     = 1 + 0.06*sin(2πt/7 + slice_phase)     # weekday/weekend
quarter_end= 1.35 if day in last 3 days of Mar/Jun/Sep/Dec else 1.0
august_dip = 0.985 for Aug dates                    # the "seasonal explanation" red herring
noise      ~ Normal(1, 0.045)
value      = base * trend * weekly * quarter_end * august_dip * noise
```

The August dip matters: it lets the drill-down demonstrate separating expected seasonality (−1.2%) from the real residual (−7.0%), which is the brief's "meaningful change vs normal noise" requirement.

### 4.3 Injected ground truth

**True cause — `deploy_sepa_v214`:**
- `ts_start = 2026-08-03T02:00Z`, source `github`, type `deploy`.
- `blast_radius = {"region": ["DACH"], "payment_rail": ["sepa"]}`.
- Effect: multiply `mrr_renewals` by **0.15** for slices matching `region=DACH AND payment_rail=sepa AND segment=Enterprise`, from Aug 3 through Aug 31 (unresolved at demo time). Mid/SMB unaffected — the gateway path is enterprise direct-debit only. This makes segment a *real* discriminating dimension for the drill-down.
- Aggregate effect on total `mrr_renewals` ≈ −8%. **Tune `slice_base` so the aggregate lands in −7.8%..−8.6%; assert this in `test_gen_data.py`.**

**Decoy 1 — `campaign_dach_cut` (the star of the demo):**
- `ts_start = 2026-08-04`, source `calendar`, type `campaign`.
- `blast_radius = {"region": ["DACH"]}` — note: *no* rail or segment constraint, and it targets acquisition.
- Effect: multiply **`new_logo_bookings`** by 0.7 for `region=DACH`, from Aug 4. **Zero effect on `mrr_renewals`.**
- Why it's dangerous: temporally near-perfect (T≈0.95), region-overlapping (C moderate). It must be beaten on **C** (blast radius is region-wide but the anomaly is rail- and segment-specific) and killed on **N** (its control — "if a DACH-wide demand shock, DACH card-rail and DACH Mid/SMB renewals should also drop" — fails).

**Decoy 2 — `pricing_us_q3`:** Aug 2, `blast_radius = {"region": ["US"]}`. Killed instantly by empty cohort intersection; it should never even become a candidate. Include it to prove the filter works.

**Distractor events (must not rank):** 8 deploys with unrelated blast radii, 2 feature flags, 1 vendor incident in APAC, 1 policy change in UK. Spread across Jul 15 – Aug 12.

**Tickets (`tickets.json`, ~120):**
- Baseline: ~2/day random accounts, keys drawn from `{ERR_TIMEOUT, BILLING_Q, LOGIN, FEATURE_REQ}`.
- Injected spike: from Aug 3, 42 tickets with `error_code = "ERR_SEPA_504"`, all `region=DACH, segment=Enterprise`, over 6 days.
- Fields: `ticket_id, created_at, account_id, region, segment, subject, body, error_code|null`. **Half the injected tickets must have `error_code=null`** and mention the failure only in prose ("direct debit keeps timing out at checkout") — this forces `normalizer.py`/`symptoms.py` to earn their keep and gives the LLM lane something real to do.

**Slack (`slack.json`, ~25):** 1 genuine `#ops-payments` alert on Aug 3 03:14 ("Frankfurt cluster SEPA latency spiking post-deploy"), 1 finance message noticing the revenue dip on Aug 9, 23 unrelated messages. Fields: `msg_id, ts, channel, author, text, permalink`.

**`ground_truth.json`:**

```json
{"true_cause_event_id": "deploy_sepa_v214",
 "true_cohort": {"region":["DACH"],"segment":["Enterprise"],"payment_rail":["sepa"]},
 "onset": "2026-08-03",
 "expected_agg_delta_pct_range": [-8.6, -7.8],
 "decoys": ["campaign_dach_cut", "pricing_us_q3"],
 "must_not_rank_top": ["campaign_dach_cut"]}
```

Only `tests/` may read this file. Assert it in `test_gen_data.py` by grepping the `ledgerlens/` package for `ground_truth` **excluding `gen_data.py`** — the generator legitimately *writes* it, so a bare grep fails on its own writer. Nothing in the package may *read* it.

---

## 5. Store — `ledgerlens/store.py`

Single DuckDB file, created idempotently.

```sql
CREATE TABLE fact_metric (
  date DATE, metric_name VARCHAR, region VARCHAR, segment VARCHAR,
  payment_rail VARCHAR, product VARCHAR, value DOUBLE
);
CREATE TABLE dim_registry (dimension VARCHAR, value VARCHAR);   -- the "universe" per dim, for complements

CREATE TABLE change_event (
  event_id VARCHAR PRIMARY KEY, event_type VARCHAR, ts_start TIMESTAMP, ts_end TIMESTAMP,
  source VARCHAR, blast_radius JSON, description VARCHAR, evidence_refs JSON,
  extraction VARCHAR, confidence DOUBLE
);
CREATE TABLE ticket (
  ticket_id VARCHAR PRIMARY KEY, created_at TIMESTAMP, account_id VARCHAR,
  region VARCHAR, segment VARCHAR, subject VARCHAR, body VARCHAR, error_code VARCHAR
);
CREATE TABLE symptom_cluster (
  cluster_id VARCHAR PRIMARY KEY, key VARCHAR, cohort JSON, first_seen DATE,
  volume INTEGER, baseline_volume DOUBLE, lift DOUBLE, sample_refs JSON
);
CREATE TABLE query_log (
  query_id VARCHAR PRIMARY KEY, sql VARCHAR, params JSON,
  result_preview VARCHAR, executed_at TIMESTAMP, label VARCHAR
);
CREATE TABLE diagnosis (
  diagnosis_id VARCHAR PRIMARY KEY, anomaly_id VARCHAR, card JSON, created_at TIMESTAMP
);
CREATE TABLE verdict (
  verdict_id VARCHAR PRIMARY KEY, anomaly_id VARCHAR, hypothesis_id VARCHAR,
  event_type VARCHAR, metric VARCHAR, verdict VARCHAR, corrected_cause VARCHAR, ts TIMESTAMP
);
```

`blast_radius` and `cohort` are stored as JSON strings; deserialize in Python. Do **not** try to do cohort algebra inside SQL — do it in `models.py` and pass a rendered WHERE clause down.

Public API:

```python
class Store:
    def __init__(self, path: Path = DB_PATH): ...
    def init_schema(self) -> None: ...
    def load_all(self, data_dir: Path) -> None: ...      # parquet + json -> tables
    def q(self, sql: str, params: dict | None = None, label: str = "") -> tuple[pd.DataFrame, str]:
        """Execute, log to query_log, return (df, query_id)."""
    def series(self, metric: str, cohort: Cohort, start: date, end: date) -> tuple[pd.Series, str]:
        """Daily summed series for a cohort. Returns (series, query_id)."""
    def dim_universe(self, dim: str) -> list[str]: ...
```

---

## 6. Query registry (provenance)

`Store.q` is the **only** path to the database. It:

1. Renders SQL with params bound (DuckDB `?`/named params — never f-string user values).
2. Computes `query_id = "q_" + sha1(sql + json(params))[:10]`.
3. Inserts into `query_log` with a human `label` and a truncated result preview (first 3 rows as text, ≤500 chars).
4. Returns the DataFrame and the id.

Every model carrying a `query_id`/`query_ids` field gets it from here. The Streamlit UI renders an "🔍 show query" expander on every evidence line by looking up `query_log`. **Acceptance test:** walk a finished `DiagnosisCard`, collect all `query_id`s, assert each exists in `query_log` and re-executing its SQL reproduces the preview.

---

## 7. Anomaly engine — `ledgerlens/anomaly.py`

### 7.1 Baseline and residual

```python
def deseasonalize(s: pd.Series) -> tuple[pd.Series, str]:
    """Return (expected_baseline, method). Uses STL if len(s) >= STL_MIN_CYCLES*period
    and s has no gaps; else rolling median (window=28, centered=False, min_periods=14)."""
```

- STL path: `STL(s, period=7, robust=True).fit()`; `expected = trend + seasonal`, `residual = s - expected`.
- Fallback path: `expected = s.rolling(28).median() * weekday_factor`, where `weekday_factor` is the trailing median ratio for that weekday over 8 weeks.

Robust z-score on residual:

```
mad   = median(|r - median(r)|) over the trailing 90d PRE-window only
z_t   = 0.6745 * (r_t - median(r_pre)) / max(mad, eps)
```

Use the pre-window (before the candidate anomaly) for `median`/`mad` so the anomaly does not inflate its own dispersion estimate. This is a common bug — write a test for it.

**Flag condition:** `z_t < -MAD_Z_THRESHOLD` for `MIN_CONSECUTIVE_PERIODS` consecutive days (v1 flags **drops only**, per `DIRECTION`). `onset` = first such day. `window` = `[onset, min(onset+13, last_date)]`.

**Why drops-only is not optional in v1:** the generator's quarter-end multiplier (1.35× for the last 3 days of Jun/Sep/...) is a *known calendar effect*, not an anomaly — but the rolling-median baseline doesn't model it, so late June would breach `+3.5` MAD for 3 consecutive days and a bidirectional detector would flag it, failing the `as_of=2026-07-31 → None` test. Correct long-term fix is a calendar-regressor baseline (Round 2); for v1, restrict to the direction the product cares about and say so in the README.

### 7.2 Hierarchical drill-down

```python
def detect(store: Store, metric: str, as_of: date) -> Anomaly | None:
    """Root-level detection on the fully aggregated metric."""

def drill(store: Store, root: Anomaly, dims: list[str]) -> list[Anomaly]:
    """Breadth-first expansion; returns all nodes including root, each with
    contribution and parent_id set."""
```

Algorithm:

```
queue = [root]; out = [root]
while queue and depth < MAX_DRILL_DEPTH:
    node = queue.pop()
    for dim in dims not yet constrained in node.cohort:
        for value in store.dim_universe(dim):
            child_cohort = node.cohort | {dim: [value]}
            series = store.series(metric, child_cohort, ...)
            if series is empty: continue
            expected, residual, z = evaluate(series, node.window)
            contribution = (actual - expected) / (node.actual - node.expected)
            if z breaches threshold and contribution >= CONTRIBUTION_FLOOR:
                child = Anomaly(..., contribution=contribution, parent_id=node.anomaly_id,
                                depth=node.depth+1)
                out.append(child); queue.append(child)
    # keep only the best dim at this level: the one whose top child has the
    # highest contribution — prevents combinatorial blowup and mirrors how an
    # analyst actually drills
```

Guards, both mandatory: skip any child slice averaging fewer than `MIN_SLICE_ROWS_PER_DAY` rows in the window (thin slices have huge natural variance and flag constantly), and skip contribution recursion entirely when `|node.actual − node.expected| < CONTRIB_DENOM_FLOOR × node.expected` (a near-zero denominator makes contributions explode). Do **not** clamp contributions to [0,1] — a child at 1.25 with a sibling at −0.25 is real information (one slice worse than the headline, another masking it).

Apply **Benjamini–Hochberg** across the p-values of the children tested at each level (convert |z| to two-sided p under normal approx) at FDR q=0.10, and record `bh_survived` on each node. Mention this in the deck; it is one function (`scipy.stats.false_discovery_control` or 8 lines by hand) and it is the correct answer to "aren't you multiple-testing?". Honest caveat for Q&A: sibling slices are positively dependent (subsets of one parent), so BH's guarantee is approximate here — frame it as a principled sanity filter on branch selection; the load-bearing rigor is the negative controls downstream, which need no distributional assumption.

**The anomaly the pipeline hands downstream** is the deepest node with the highest `contribution` product along its path (call it the *focal anomaly*). For the demo this must resolve to `{region: DACH, segment: Enterprise, payment_rail: sepa}`.

**Acceptance (`test_anomaly.py`):**
- focal anomaly cohort == `ground_truth.true_cohort`
- `focal.onset == 2026-08-03`
- root `delta_pct` within `expected_agg_delta_pct_range`
- August seasonal component alone must NOT trigger a flag: assert that running `detect` on `as_of = 2026-07-31` returns `None`.

---

## 8. Change Ledger — `ledgerlens/ledger/`

### 8.1 `connectors.py` — deterministic (no LLM)

One function per source, each returning `list[ChangeEvent]`:

```python
def from_deploys(path) -> list[ChangeEvent]      # github json: {sha, merged_at, service, regions, rails, title, url}
def from_flags(path) -> list[ChangeEvent]        # launchdarkly json: {key, enabled_at, targeting: {...}}
def from_campaigns(path) -> list[ChangeEvent]    # calendar csv/json: {name, start, end, geo, objective}
def from_pricing(path) -> list[ChangeEvent]      # pricing table diff: {sku, region, old, new, effective}
```

Blast radius derivation is a **declared mapping**, not inference. Example for deploys:

```python
blast_radius = {}
if d["regions"] != ["*"]: blast_radius["region"] = d["regions"]
if d.get("rails"):        blast_radius["payment_rail"] = d["rails"]
if d.get("segments"):     blast_radius["segment"] = d["segments"]
```

Document in `README.md` that in production these come from deploy metadata / flag targeting rules / campaign geo settings — this is the "enterprises already have this data" argument and it is the crux of the pitch.

### 8.2 `normalizer.py` — LLM call site #1

Purpose: turn Slack messages and error-code-less tickets into `ChangeEvent` (Slack) or nothing (tickets → symptoms lane). **Format normalization only.** The prompt must forbid relevance judgments.

```python
def normalize_slack(messages: list[dict], dims: dict[str, list[str]]) -> list[ExtractedSignal]:
```

```python
class ExtractedSignal(BaseModel):        # lives in models.py
    is_change_event: bool
    event: ChangeEvent | None            # blast-radius rules below apply unchanged
    entities: list[str]                  # ["Frankfurt cluster"]
    signal: str | None                   # "payment latency"
    suggested_link: str | None           # "deployment -> latency" — narrative color ONLY, never scored
    confidence: float
```

The extraction is richer than pure formatting (entities, signal, suggested relationship — this is the "AI understands messy business data" slide made real), but the *authority* is unchanged: only `event` enters the ledger, blast-radius omission rules still apply, and `suggested_link` may appear in narration as color, never in scoring.

Single batched call, structured output. System prompt skeleton:

```
You convert operational chat messages into structured change events.
A change event is a DELIBERATE OR OBSERVED CHANGE to the business
(deploy, config change, incident, vendor outage, policy change).
Complaints, questions, and observations about metrics are NOT change events.
For each message that IS a change event, emit:
  event_type, ts_start (from the message ts), description (<=20 words),
  blast_radius using ONLY these dimension values: {dims}
If a dimension is not explicitly determinable from the text, OMIT that key.
Do NOT infer a dimension from plausibility. Do NOT rank or judge importance.
Return JSON array matching the schema. Empty array is a valid answer.
```

Set `extraction="llm"`, `confidence=0.7`. Validate with Pydantic; drop any event whose `blast_radius` contains a value not in `dims` (hallucinated dimension values are the #1 failure mode here — test it with an adversarial fixture).

**No-key fallback:** regex for `#ops-*` channels + keyword list (`deploy`, `rollout`, `outage`, `incident`, `migrat`) with blast radius from any literal dimension value found in the text. The demo must be reproducible without a key.

### 8.3 `symptoms.py` — ticket clustering (no LLM)

```python
def cluster(store: Store, window: Window) -> list[SymptomCluster]:
```

1. Key = `error_code` when present; else derive one by normalizing `subject` (lowercase, strip digits/punct, drop stopwords, take the 3 highest-IDF tokens joined by `_`). This deterministic path must recover the `ERR_SEPA_504` cohort from the prose-only tickets — verify in `test_ledger.py` that ≥80% of the 21 prose tickets land in the same cluster as the coded ones (merge clusters whose token-Jaccard ≥ 0.6).
2. Cohort = the modal `(region, segment)` of the cluster's tickets, kept only where ≥70% of tickets agree.
3. `baseline_volume` = trailing 28-day mean daily volume for the same key before `window.start`; `lift = volume / max(baseline,0.5)`.
4. Return clusters with `lift >= 3.0` and `volume >= 5`.

Symptoms are **evidence attached to hypotheses**, never candidates themselves.

---

## 9. Hypothesis engine — `ledgerlens/hypothesis.py`

### 9.1 Candidate generation

```python
def candidates(store: Store, a: Anomaly) -> list[ChangeEvent]:
```

```sql
SELECT * FROM change_event
WHERE ts_start <= ?anomaly_window_end
  AND ts_start >= ?anomaly_onset - INTERVAL ?lookback DAY
```
then in Python: keep events where `cohort_intersect(event.blast_radius, a.cohort) is not None`.

`pricing_us_q3` must be eliminated here (region US ∩ region DACH = ∅). Assert it.

### 9.2 The five components

All return `[0,1]`.

**T — Temporal.** With `lag = (a.onset - event.ts_start.date()).days`:
```
T = 0                       if lag < 0            # event after onset: cannot cause
  = 1.0                     if lag == 0
  = exp(-lag / 3.0)         if lag > 0
```
An event still in effect (`ts_end is None`) that started before onset keeps its score; an event that *ended* before onset gets `T *= 0.3`.

**C — Cohort match.** Not raw Jaccard on predicates — Jaccard on the **rows they select**, so a region-wide blast radius is correctly penalized against a rail-specific anomaly:
```
A = row-set of a.cohort in the anomaly window
B = row-set of event.blast_radius in the same window
C = |A ∩ B| / |A ∪ B|
```
Implement by counting rows with `cohort_rows` for A, B, and the intersection cohort; `|A ∪ B| = |A| + |B| - |A∩B|`.

*This is the component that beats the marketing decoy.* `campaign_dach_cut` covers all of DACH (all segments, all rails, both metrics' slices) while the anomaly is DACH×Enterprise×SEPA → C ≈ 0.11. The deploy covers DACH×SEPA → C ≈ 0.33 (still <1 because it doesn't constrain segment). Verify these orderings in `test_hypothesis.py`.

**D — Dose–response.** Split the intersection into sub-cohorts by the dimension with the widest exposure variance; Spearman-correlate *exposure share* against *impact magnitude*:
```
for each sub-slice s in intersect(a.cohort, event.blast_radius) expanded by dim d:
    exposure(s) = fraction of s's rows inside event.blast_radius
    impact(s)   = -delta_pct(s) over the anomaly window
D = max(0, spearman(exposure, impact))     # 0.5 if <3 sub-slices (uninformative)
```

**N — Negative controls.** `N = passed / total` from `controls.py` (§9.4). If any control with `prediction="should_be_flat"` shows `|observed_delta_pct| > 5%` in the same direction as the anomaly, set `rejection_reason` and force `N = 0`.

**P — Learned prior.** From `learning.py`: `P = Beta(α, β).mean()` for `(event_type, metric)`, initialized `α=β=1` → 0.5.

### 9.3 Scoring and ranking

```python
def score(store, a: Anomaly, ev: ChangeEvent, symptoms: list[SymptomCluster]) -> Hypothesis
def rank(store, a: Anomaly) -> list[Hypothesis]     # sorted desc by total
```

`total = ComponentScores.total(SCORE_WEIGHTS) × ev.confidence` — deterministic events (`confidence=1.0`) are unaffected; LLM-extracted events carry their 0.7 penalty into the ranking, and the UI badges them "blast radius inferred — verify". This consumes the provenance fields that §3 defines (previously a declared-but-unused gap).

Attach a `SymptomCluster` to a hypothesis when `cohort_intersect(cluster.cohort, event.blast_radius)` is non-empty and `cluster.first_seen` ∈ `[onset-1, onset+3]`. Symptoms do not change the score; they are corroborating narrative evidence. (Keeping them out of the score avoids double-counting the same signal that C already measures — say this if a judge asks.)

If `max(total) < SCORE_FLOOR`: return the ranked list but set a pipeline flag `no_confident_cause=True`; the card must then say plainly that no ingested change explains the anomaly and list which source systems are and are not connected. **Do not let the LLM paper over this** — `narrate.py` receives the flag and has a separate template branch.

### 9.4 `controls.py`

```python
def generate(store: Store, a: Anomaly, ev: ChangeEvent) -> list[ControlResult]:
```

Rules, in order:

1. **Rail/dimension complement.** For each dimension `d` constrained in `ev.blast_radius` but where the anomaly cohort has siblings: build `cohort_complement(a.cohort, d, universe)` restricted to the anomaly's other dims. Prediction `should_be_flat`.
   → *DACH × Enterprise × card* for the SEPA deploy. Expected flat. ✓
2. **Segment siblings.** If `ev.blast_radius` does not constrain `segment` but the anomaly does, build the same cohort with the other segments. Prediction: `should_also_drop` (a segment-agnostic cause should hit all segments).
   → For `campaign_dach_cut`: *DACH × Mid/SMB × renewals* should also drop. It doesn't. ✗ → kills the decoy.
3. **Geographic complement.** Same segment+rail in regions outside the blast radius. Prediction `should_be_flat`.
4. **Objective mismatch.** If `ev.event_type == "campaign"`, additionally test the campaign's own target metric (`new_logo_bookings`) in the blast-radius cohort with prediction `should_also_drop` *for that metric*. This surfaces the honest finding: the campaign cut **did** cause something real — a 30% new-logo drop — just not the renewals anomaly. Put this in the video; "it found a second, different problem" is a memorable beat.

Evaluate each control by computing `delta_pct` over the anomaly window vs. the deseasonalized expectation, using the same `anomaly.evaluate` machinery, and `passed = (|delta| < 5%)` for `should_be_flat`, `(delta < -5%)` for `should_also_drop`.

---

## 10. Effect size — `ledgerlens/effect.py`

Difference-in-differences with a bootstrap interval. No causal-inference library.

```python
def estimate(store, a: Anomaly, control_cohort: Cohort) -> EffectEstimate
```

1. Pre-window = 56 days before `a.onset`. Build `y_pre` (treated cohort daily series) and `x_pre` (control cohort daily series; use the passing `should_be_flat` control with the largest row count).
2. Fit `y = β·x` through the origin (ratio estimator, `β = sum(y_pre)/sum(x_pre)`) — simpler and more robust than OLS at this sample size. Record `pre_fit_quality` = R² of `β·x_pre` vs `y_pre`. **Label it "pre-period fit quality" in the UI, never "causal strength."**
3. Counterfactual over the anomaly window: `ŷ_t = β · x_t`. `impact = Σ(y_t − ŷ_t)`.
4. Bootstrap: resample pre-window days with replacement `BOOTSTRAP_ITERS` times, recompute β, recompute impact; take 2.5/97.5 percentiles.

Expected demo output ≈ `-410,000 ± 40,000` (tune `slice_base` so the number is plausible and round-ish). Assert the true impact from `ground_truth` falls inside the CI in `test_effect.py`.

---

## 11. Ambiguity, learning, narration, orchestration

### 11.1 `ambiguity.py`

```python
def discriminate(store, a: Anomaly, h1: Hypothesis, h2: Hypothesis) -> DiscriminatingTest
```

Triggered when `h1.total - h2.total < AMBIGUITY_EPSILON`.

1. Find dimensions where the two blast radii differ. For each candidate slice in the symmetric difference, ask: does H1 predict a drop there and H2 not (or vice versa)?
2. If such a slice exists **and has data** → `resolvable_now=True`, build the SQL, run it via `Store.q`, write the verdict into `result`, and re-score (the resolved control feeds back into N for the losing hypothesis).
3. If no slice in the current data separates them → `resolvable_now=False`, and emit `proposed_experiment` from a small template table keyed on event_type pairs, e.g. deploy vs. external-demand → *"Re-route 5% of DACH SEPA renewal retries through the v2.1.3 connector for 24h; if success rate recovers, H1 is confirmed."* `owner_hint` from `event.source` (`github`→"service owning team", `calendar`→"growth marketing").

For the demo, the SEPA vs. campaign pair **is** resolvable now — good, it shows the mechanism working end to end. Add a second scripted anomaly in the generator (a smaller Nordics dip in July caused by *either* a pricing change or a competitor entry, with no separating slice) so the UI can also demonstrate the unresolvable branch. Keep this optional if time-boxed.

### 11.2 `learning.py`

```python
def prior(store, event_type: str, metric: str) -> float   # Beta mean, α=β=1 default
def record(store, anomaly_id, hypothesis_id, verdict: Literal["confirm","reject","correct"],
           corrected_cause: str | None) -> None
```

`confirm` → α += 1 for `(event.event_type, metric)`; `reject` → β += 1. Derive α/β by counting rows in `verdict` at read time (no separate state table — keeps it auditable). The UI shows "prior for deploy→mrr_renewals: 0.50 → 0.67 after your confirmation," which is the moat slide made concrete on camera.

### 11.3 `narrate.py` — LLM call site #2

```python
def narrate(payload: NarrationPayload, no_confident_cause: bool) -> DiagnosisCard
```

`NarrationPayload` is a dict of **already-computed** values: focal anomaly, top-3 hypotheses with component scores and control results, effect estimate, symptom clusters, discriminating test.

Prompt rules to encode in the system prompt:
- "You are writing an incident diagnosis for a business analyst. Every number you use MUST appear verbatim in the payload. You may not compute, round, or estimate any figure."
- "For each `EvidenceStep`, copy the `query_id` from the payload item you are describing."
- "State the rejected hypotheses and the specific control observation that rejected them."
- "Never use the words 'caused by' for a hypothesis with total < 0.7; use 'most consistent with'."
- Output must validate against `DiagnosisCard`; on validation failure, retry once with the errors appended, then fall back to template.

**Template fallback** (`generated_by="template"`) must produce a genuinely readable card — it is what runs in tests and, if the API hiccups, on stage. Write it first, treat the LLM as the upgrade.

### 11.4 `investigator.py` — LLM call sites #3 and #4 (additive lane)

```python
def propose_tests(payload: dict, budget: int = LLM_TEST_BUDGET) -> list[ProposedTest]
def unverified_causes(payload: dict) -> list[UnverifiedHypothesis]
def explore(store, focal: Anomaly, budget: int = EXPLORER_QUERY_BUDGET) -> list[ProposedTest]   # optional, cut first
```

- **`propose_tests`**: input is the focal anomaly + top-3 hypotheses + the dimension universe + metric list. The LLM may ONLY fill the four templates in `ProposedTest`; params are validated against `dim_registry` before execution (reject silently on unknown values — hallucinated dimension values are the expected failure mode). A deterministic executor maps each template onto the existing `controls`/`anomaly` machinery and fills `result`. Results render in a separate "AI-proposed checks" table. **They do not feed the N score** — the acceptance test's ranking must be reproducible with zero LLM calls. Rationale to say out loud: the rules cover the checks we anticipated; the LLM covers the ones we didn't.
- **`unverified_causes`**: always runs when a key is present. Output renders in a visually distinct amber panel titled "Possible causes we cannot verify with connected data", each item naming the missing source. This is the honest lane for ledger blind spots (competitor moves, macro shifts) and the answer to "what if the cause was never recorded?"
- **`explore`** (optional): auto-runs only when `no_confident_cause` — a bounded pass (≤ budget queries) proposing new slices or alternative control comparisons via the same template vocabulary. Every finding re-enters standard verification and renders labeled *Exploratory*. Not an open-ended agent; no free-form SQL anywhere in the system.

### 11.5 `pipeline.py`

```python
def run(metric: str = "mrr_renewals", as_of: date = date(2026,8,17)) -> DiagnosisCard:
    store = Store(); store.init_schema()
    root = anomaly.detect(store, metric, as_of)
    if root is None: return DiagnosisCard.no_anomaly()
    nodes = anomaly.drill(store, root, ["region","segment","payment_rail","product"])
    focal = anomaly.focal(nodes)
    symptoms = symptoms_mod.cluster(store, focal.window)
    hyps = hypothesis.rank(store, focal, symptoms)
    top = hyps[0] if hyps else None
    if top and top.total >= SCORE_FLOOR:
        control = controls.best_flat_control(top)
        top = top.model_copy(update={"effect": effect.estimate(store, focal, control.cohort)})
    dt = ambiguity.discriminate(store, focal, hyps[0], hyps[1]) if ambiguous(hyps) else None
    return narrate.narrate(build_payload(...), no_confident_cause=(top is None or top.total < SCORE_FLOOR))
```

Runtime budget: **< 5 s** without LLM calls, < 15 s with them. If drill-down exceeds this, cache series inside `Store` with a plain dict keyed on `(metric, canonical_cohort_key(cohort), start, end)` — where the key sorts dims and values into a tuple. Do **not** slap `functools.lru_cache` on the method: `self` and dict-typed cohorts are unhashable and the naive attempt is a 20-minute detour.

---

## 12. Build order with checkpoints

| Phase | Build | Passing test |
|---|---|---|
| 1 | `config.py`, `models.py` (cohort algebra first), `store.py` schema | `test_models.py`: intersect/complement/predicate unit tests incl. empty-intersection and unconstrained-key cases |
| 2 | `gen_data.py` + load | `test_gen_data.py`: aggregate delta in range; ground truth file written; package doesn't import it |
| 3 | `anomaly.py` | `test_anomaly.py`: focal cohort == ground truth; onset exact; no false flag at 2026-07-31 |
| 4 | `ledger/connectors.py`, `symptoms.py` | `test_ledger.py`: 12 events ingested; ERR_SEPA_504 cluster recovers prose tickets; lift ≥ 3 |
| 5 | `hypothesis.py` candidates + T, C | `test_hypothesis.py`: US pricing filtered out; C(deploy) > C(campaign) |
| 6 | `controls.py` + N, D, P | `test_controls.py`: campaign gets `rejection_reason`; deploy passes ≥3 controls |
| 7 | `effect.py` | `test_effect.py`: true impact inside CI |
| 8 | `narrate.py` template branch + `pipeline.py` | `test_pipeline.py` **(acceptance)**: top hypothesis == `deploy_sepa_v214`; `campaign_dach_cut` in `rejected`; every `query_id` resolvable and re-executable |
| 9 | `ambiguity.py`, `learning.py`, LLM branches (rich normalizer, narrator) | manual + adversarial fixture for normalizer |
| 9b | `investigator.py` (propose_tests, unverified_causes; `explore` last) | template params rejected on unknown dim values; ranking unchanged with/without key |
| 10 | `app.py` incl. manual slice targeting + provenance badges | manual: full click-through in < 60 s |

Phases 1–8 are the product. 9–10 are the demo. If time runs out, ship 8 with the template narrator.

**Deadline reality (Round 1 = deck + video by 23:59 Aug 16):** nothing in this file is required for tonight's submission — the brief demands a concept, not code. Build order for tonight is deck → video → submit; this spec is executed afterwards for Round 2 / prototype screenshots. **MVP-for-video path** if hours remain after submission material is done: phases 1–6 + template narrator + a bare Streamlit page (skip effect, ambiguity, learning, investigator — present them as design in the video).

---

## 13. Streamlit UI — `app.py`

Single page, four vertical sections. Keep it plain; the content is the impressive part.

1. **Anomaly header.** Metric name, `delta_pct` in red, window, and one line: *"Expected −1.2% (August seasonality). Unexplained: −7.0% (z = −5.8)."* This one line is the "meaningful change vs. noise" requirement, visible in the first two seconds of the video.
2. **Attribution.** Plotly treemap of the drill-down tree, sized by `|delta_abs|`, colored by `contribution`. Clicking a node re-runs the pipeline focused there (nice-to-have; static is fine).
3. **Hypotheses.** One card per hypothesis, sorted. Each shows: description, total score, a horizontal bar per component (T/C/D/N/P) with the weight printed, the control table (name / prediction / observed / ✓✗), attached symptom clusters, and an expander per evidence line showing the SQL from `query_log` and its result. Rejected hypotheses render greyed with the failing control highlighted — **this is the shot for the video, make it look good.**
4. **Diagnosis + actions.** The narrated card, the effect estimate with CI, the discriminating test (if any), and Confirm / Reject / Correct buttons that call `learning.record` and immediately re-render the updated prior.

Between sections 3 and 4, two investigator panels when present: the "AI-proposed checks" table (template, params, rationale, result, ✓✗) and the amber "Possible causes we cannot verify with connected data" panel. Badge every hypothesis card with provenance: **Recorded** (deterministic connector), **Inferred — verify** (LLM extraction, shows confidence), **Exploratory** (explorer lane).

Sidebar: metric selector, `as_of` date, the weight dictionary (read-only), a "Regenerate data" button, and **"Investigate a slice manually"** — pick metric, dimension values, and a window, and the pipeline runs with detection bypassed (detection is advisory, not gating; this is also the honest answer to detection blind spots like slow drifts and interaction effects).

---

## 14. Non-goals (do not build)

Auth, multi-tenancy, real connectors to GitHub/Zendesk/Slack APIs, a graph database, vector search, agent frameworks (the bounded `explore` pass is a fixed-budget loop over validated templates, not an agent), free-form LLM-generated SQL, streaming ingestion, forecasting of future metrics, any causal-inference library, model training beyond the Beta counting in `learning.py`, and any LLM pass that re-ranks hypotheses after seeing evidence — the scorer already re-ranks on evidence (N, D); an LLM override reintroduces the exact failure mode this design exists to prevent.

## 15. README requirements

The `README.md` must contain: the one-paragraph pitch, `pip install -e . && python -m ledgerlens.gen_data && streamlit run app.py`, a diagram of the pipeline, the honest-claims section ("this ranks evidence, it does not prove causation — here is exactly what each component measures"), and the blast-radius-in-production note from §8.1. Judges who click into the repo should hit the honesty statement early; it is a feature, not a hedge.


---

## 16. Pitfall register (found on review — each fixed above or explicitly scoped out)

| # | Pitfall | Consequence if ignored | Resolution |
|---|---|---|---|
| 1 | Quarter-end 1.35× spike vs. bidirectional flagging | False positive every quarter close; the `as_of=2026-07-31 → None` test fails | `DIRECTION="drop"` in v1 (§7.1); calendar-regressor baseline in Round 2 |
| 2 | `cohort_rows` not pinned to a metric | Blast radii unconstrained on metric get |B| inflated by other metrics' rows; C scores silently wrong | `metric` parameter mandatory (§3) |
| 3 | Ground-truth grep matches its own writer | The isolation test fails on day one | Grep excludes `gen_data.py` (§4.3) |
| 4 | Near-zero parent delta in contribution | Division blow-up, garbage recursion | `CONTRIB_DENOM_FLOOR` guard (§7.2) |
| 5 | Thin slices (3 rows/day) | Constant false flags deep in the tree | `MIN_SLICE_ROWS_PER_DAY` gate (§7.2) |
| 6 | Clamping contribution to [0,1] | Hides masking (one slice worse than headline, sibling offsetting) | Don't clamp; documented (§7.2) |
| 7 | `lru_cache` on `Store.series` | Unhashable `self`/dict args; 20-minute detour | Dict cache with canonical key (§11.5) |
| 8 | Offsetting moves cancel at the root | Real incident never triggers detection | Known v1 limitation; manual slice targeting covers it now (§13); scheduled level-1 detection in Round 2 |
| 9 | LLM hallucinating dimension values (normalizer, investigator) | Fabricated blast radii / test params | Reject values outside `dim_registry`; confidence multiplier + UI badge (§8.2, §9.3, §11.4) |
| 10 | Any LLM lane in the acceptance path | Nondeterministic demo; flaky tests; blank screen on stage | Additive-only rule (§0.2); full suite passes with no API key |
| 11 | BH assumes independence; siblings aren't | Overstated statistical guarantee if pitched as exact | Framed as approximate sanity filter; controls carry the rigor (§7.2) |
| 12 | Row-count Jaccard weighs slices equally regardless of value | A tiny-revenue slice counts as much as a huge one in C | Acceptable for demo (documented); Round 2: weight rows by baseline revenue |
