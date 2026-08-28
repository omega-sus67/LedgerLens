# LedgerLens — Task Flow

Implementation detail for every remaining item before the **Aug 30** submission.
Written **Aug 28** against the repo as it stands, superseding the schedule in
`improvements.md` (which assumed Aug 26–27 work that did not land).

Purpose: something the team can read, argue with, and split up. Each task below is
self-contained — goal, the brief row it closes, files touched, subtasks, how it is
tested, and what could go wrong.

---

## 0. Where the repo actually is

**Verified Aug 28.** 96 tests pass. Repo is **public**
(`gh repo view` → `"visibility":"PUBLIC"`). `details/` (contest PDFs) is correctly
untracked.

Since `improvements.md` was written, exactly one thing landed, and only its back half:

- `ledgerlens/contracts.py` — new, untracked. Complete and well-built: `KpiContract`,
  `LineageStep`, `AccessRule`, `Thresholds`, `CONTRACTS` for both KPIs, plus
  `get()` / `thresholds()` / `hidden_dims_for()` / `visible_drill_dims()`.
- `ledgerlens/anomaly.py` — modified. `scan_for_onset()` now takes a `Thresholds`,
  and `detect()` / `drill()` pass `contracts.thresholds(metric)`.

But `contracts.py` has **no UI surface and no tests**, and `visible_drill_dims()` is
called by nothing. Housekeeping that also landed: streamlit pinned `<1.63`,
`test_app.py` given an absolute path.

### Two things that will bite us

1. **`.gitignore` now contains `*.md`.** The three existing docs
   (`README.md`, `IMPLEMENTATION_SPEC.md`, `businessintelligence-ai-redesign.md`) are
   already tracked so they still commit — but every **new** markdown file is silently
   ignored. **This file included.** Fix before writing the business proposal:

   ```gitignore
   *.md
   !README.md
   !taskflow/*.md
   !docs/*.md
   ```

   Verify with `git check-ignore -v taskflow/taskflow.md`.

2. **Nothing since Aug 16 is pushed.** `pushedAt` is `2026-08-16`. All of
   `contracts.py` and the anomaly wiring is uncommitted local work — one lost laptop
   from being gone.

### Running the tests on this machine

The ROS 2 install poisons `PYTHONPATH`. Without stripping it, pytest dies at
collection with `ModuleNotFoundError: No module named 'yaml'`:

```bash
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q
```

Worth adding to `CLAUDE.md`.

---

## Task order

Ordered so each task unblocks the next, not by the P0/P1 tiers in `improvements.md`.
Items 1–7 are literal rows on the judges' Minimum Prototype Expectations list.

| # | Task | Closes | Est. |
|---|---|---|---|
| 1 | Finish the KPI semantic contract | contract, grains/cadences, freshness | 2h |
| 2 | Personas + `Action` schema reshape | persona narratives, levers/decision rights | 3h |
| 3 | Third KPI with sparse history | 3–5 KPIs, sparse-history scenario | 3h |
| 4 | Role-based entitlement | security/entitlement scenario | 1–2h |
| 5 | Learning-loop UI | learns from feedback | 2h |
| 6 | Telemetry panel | latency/cost, LLM vs non-LLM in the UI | 1–2h |
| 7 | Abstention demo path | abstains when evidence insufficient | 1h |
| 8 | Model-id fix + one real LLM call | model choice & cost reasoning | 3h |
| 9 | `effect.py` — diff-in-diff + bootstrap CI | materiality as stat + business impact | 3h |
| 10 | Ingest `slack.json` | heterogeneous sources | 2h |
| 11 | `ambiguity.py` — discriminating test | uncertainty handling | 3h |
| 12 | Submission package | repo, README, video, proposal | 4h |

**Cut line if behind:** drop 11, then 10, then 9, then 8. Never drop 1–7 — those are
checklist rows, and a missing checklist row is a zero, not a deduction.

---

## Task 1 — Finish the KPI semantic contract

**Goal:** `contracts.py` stops being dead metadata and becomes a visible, tested,
judge-facing surface. Closes three brief rows at once: the contract itself,
"different grains / refresh cadences", and "evidence: freshness … lineage".

**Files:** `ledgerlens/contracts.py`, `app.py`, `tests/test_contracts.py` (new),
`tests/test_app.py`

### 1.1 — `tests/test_contracts.py`

New file. Follow the house style: plain asserts, docstring says *why* the test exists.

- every name in `config.METRICS` has an entry in `CONTRACTS`
- `Thresholds()` field-by-field equals the `config` constants. **This is the important
  one** — it is the invariant the already-landed `anomaly.py` refactor rests on
  ("every default is exactly the global constant, so an unset field can never change
  detection behaviour"), and right now nothing guards it
- the `grain_dims` and `AccessRule.hidden_dims` validators raise on an unknown dim
- `visible_drill_dims("growth")` on `mrr_renewals` drops `payment_rail`;
  an unknown role returns all of `config.DRILL_DIMS` (fail-open, as documented)
- `get("nope")` raises `KeyError`; `thresholds("nope")` returns defaults
- every `related_event_types` entry is an `event_type` that actually appears in the
  generated ledger — guards contract drift against `gen_data.py`

### 1.2 — `contracts.freshness(store, metric, as_of)`

New function. For each `LineageStep`, report the newest data actually present versus
`as_of`, so the UI shows **measured** freshness beside the **declared**
`refresh_cadence`. Reuses the existing store API and schema:

- `kind="metric"` → `store.max_date(metric)` (store.py:200)
- `kind="context"` → `SELECT max(ts_start) FROM change_event WHERE source = $s`
- `kind="symptom"` → `SELECT max(created_at) FROM ticket`

Return a frozen model: `source_system`, `declared_cadence`, `last_seen`, `lag_days`,
`kind`. Issue through `store.q()` so freshness numbers are query-logged like every
other number on the page and show up in `pipeline.card_query_ids()`.

**Decide:** freshness relative to `as_of`, not today. The demo is a time-travel replay
pinned at `DEFAULT_AS_OF = 2026-08-17`; measuring against the wall clock would print
"1181 days stale" on stage.

### 1.3 — "📜 Contract" expander in `app.py`

Collapsed `st.expander`, placed directly after the focal-cohort `st.caption(...)` and
before the first `st.divider()`. Contents:

- definition, unit, owner, status
- `calculation_sql` via `st.code(..., language="sql")`
- known drivers, as bullets
- thresholds table — the values in force **for this KPI**
- lineage table: source → artifact → table → grain → declared cadence → measured
  freshness (1.2)
- access policies: `policy_id`, role, hidden dims, reason

Use `contracts.get(metric)` (strict) so an ungoverned KPI fails loudly instead of
rendering an empty box.

Also switch the sidebar "Thresholds" panel from bare `config.*` constants to
`contracts.thresholds(metric)` — two lines, and it makes the contract visibly *in
force* rather than decorative.

### 1.4 — Extend `tests/test_app.py`

Against the existing module-scoped `app` fixture: the expander renders, the
calculation SQL appears, the freshness column carries a real number.

**Risk:** the `st.cache_resource` on `load()` keys on `(metric, as_of)` only. Anything
added later that changes rendering (persona, role, toggles) must join that cache key
or the UI will serve stale cards. Flagged here because Tasks 2, 4, 5 and 7 all hit it.

---

## Task 2 — Personas + `Action` schema

**Goal:** two audiences, *identical evidence*. That sentence is the pitch to judges:
"different narratives, same `query_id`s."

**Files:** `ledgerlens/models.py`, `ledgerlens/narrate.py`, `app.py`, `tests/`

### 2.1 — Reshape `Action` (models.py:269)

Currently `priority / owner / action / basis`. The brief wants
`driver → controllable lever → action → expected impact → owner → confidence →
monitoring plan`. Add `lever: str`, `expected_impact: str`, `confidence: float`,
`monitoring: str`. Keep `basis` — it carries the `query_id` and is the traceability
hook.

All four construction sites are in `narrate.py` (≈183, 192, 209, 275). Existing
`OWNER_BY_SOURCE` already supplies `owner`.

### 2.2 — Persona templates in `narrate.py`

`narrate()` gains a `persona` argument; `_cause_card` / `_no_cause_card` branch on it.
The narrator is already template-based, so this is a second template, not new
machinery.

- **CFO** — headline in dollars, seasonality-adjusted, one action, monitoring plan, no
  SQL jargon, no event ids in prose.
- **Payments on-call** — event id first, blast radius, affected rail, rollback as the
  P0 action, full control table.
- **Analyst** (default) — today's card, unchanged.

`NarrationPayload` is unchanged; only rendering differs. That is the property the
tests should assert.

### 2.3 — Sidebar selector + tests

`st.sidebar.selectbox("Persona", ...)`, threaded into `load()`'s cache key.

Test: for the same `(metric, as_of)`, the CFO and on-call cards have **different
summary text** but **identical `pipeline.card_query_ids()`**. That single assertion is
the whole claim, machine-checked.

---

## Task 3 — Third KPI with sparse history

**Goal:** one change covers two checklist rows — lifts us to 3 KPIs *and* produces the
sparse-history scenario.

**Files:** `ledgerlens/gen_data.py`, `config.py`, `ledgerlens/contracts.py`,
`ledgerlens/pipeline.py`, `app.py`

- Add `payment_success_rate` to the generator with **~45 days** of history — below
  `config.DETECT_WARMUP_DAYS`, deliberately.
- Add to `config.METRICS` and give it a `KpiContract` with
  `status="sparse_history"`. A rate metric bounded near 98% needs its own
  `min_abs_delta_pct` — the contract's per-KPI thresholds exist precisely for this.
- `scan_for_onset()` already returns `None` when `len(s) < th.warmup_days`, so
  detection declines on its own. The work is making the *decline* legible: the card
  must say **"insufficient history for automatic detection — manual window analysis
  only, wider uncertainty"** rather than rendering a blank success box.
- `pipeline.run()` already supports the manual path (`cohort` + `window` bypass
  detection). Expose it in the UI for sparse KPIs.

**Test:** `detect()` returns `None` for the sparse KPI; the manual path still produces
a full card; the UI shows the insufficient-history banner.

**Risk:** the biggest task on the list. `gen_data.py` is ~500 lines of carefully
seeded generation and `ground_truth.json` must stay consistent. Do not let a new
metric perturb the existing series — the acceptance test in `test_pipeline.py`
asserts the exact incident and the exact decoy.

---

## Task 4 — Role-based entitlement

**Goal:** redaction *with provenance* — the auditability story the rest of the system
already tells.

**Files:** `app.py`, `ledgerlens/pipeline.py`, `ledgerlens/anomaly.py` (probably not)

The machinery exists. `contracts.visible_drill_dims(role)` returns `DRILL_DIMS` minus
policy-hidden dims, and `anomaly.drill(store, root, dims)` already takes a `dims`
list — `pipeline.run()` just needs to pass the role-filtered list instead of
`config.DRILL_DIMS`.

The visible part is the **honest refusal**: the card must show

> 2 deeper slices redacted by policy `fin.rail_detail` — payment-rail revenue splits
> are finance-restricted

with the policy id and reason pulled from the `AccessRule`, *not* silently drop rows.
The existing contract already carries `fin.rail_detail` hiding `payment_rail` from
`growth`.

Ties to Task 2: role comes from the persona selector.

**Test:** with role `growth`, no returned node's cohort contains a `payment_rail` key;
the redaction notice names the policy id.

---

## Task 5 — Learning-loop UI

**Goal:** prove objective #7 on camera — a click that moves a number.

**Files:** `app.py`, `tests/`

`learning.record()` and the `verdict` table already exist and are unused.

- Confirm / Reject / Correct buttons on each hypothesis card in `render_hypothesis()`
- on click: `learning.record(...)` → `st.cache_resource.clear()` → `st.rerun()`
- `learning.prior()` counts `verdict` rows at read time, so the **P** component moves
  with no other wiring: Beta(1,1)=0.50 → one confirm → Beta(2,1)=**0.67**

Show the before/after explicitly next to the P bar. That is a 15-second video beat.

**Risk:** `verdict` rows persist in `data/ledgerlens.duckdb`. Repeated demo clicks will
drift the priors away from the numbers in the README and in `test_app.py`
(`scores[0] == "0.700"`). Need a "reset feedback" control, or delete the db before
recording. **Decide this before the video.**

---

## Task 6 — Telemetry panel

**Goal:** the runtime-constraints row, and it doubles as the LLM-vs-non-LLM breakdown
*in the UI* where judges see it (today it is only in the README).

**Files:** `ledgerlens/pipeline.py`, `app.py`

- wrap each `pipeline.run()` stage in `time.perf_counter()` — detect, drill, symptoms,
  rank, narrate — and return the timings on the card
- count registered queries: `len(pipeline.card_query_ids(card))`
- LLM calls and tokens: **0** in offline mode. Say so plainly and turn it into a
  strength: *"this diagnosis: 0 LLM calls, $0.000 — every number came from a logged
  SQL query. With the narrator enabled: 1 call, ~2.1k tokens, ~$0.01."*

One `st.expander("⏱ telemetry")`. `tests/test_pipeline.py:130` already uses
`perf_counter` for a latency assertion — same pattern.

---

## Task 7 — Abstention demo path

**Goal:** abstention **demonstrated**, not described. The code path already exists;
it just has no way to reach it without editing source.

**Files:** `app.py`, `ledgerlens/pipeline.py`

Sidebar toggle: *"simulate: deploy source not connected"* → drops `source="github"`
events from candidate generation → nothing clears `config.SCORE_FLOOR` (0.45) →
`narrate._no_cause_card()` renders, and it **already** emits the right thing: what is
connected vs not, plus a P1 action to *"connect {missing} so the next incident of this
shape has candidates to test"*.

Cheapest item on the list — the payoff is entirely in `_no_cause_card` already being
written. Must join the `load()` cache key.

---

## Task 8 — Model id + one real LLM call

**Goal:** it is an AI challenge and the demo currently makes zero model calls.

**Files:** `config.py`, `ledgerlens/narrate.py`

- **`config.py:100` — `MODEL = "claude-sonnet-4-6"` is not a valid model id.**
  Use `claude-sonnet-5`. One line, and a judge who knows the API will notice.
- Ship the narrator's LLM branch: structured output, Pydantic-validated, template
  fallback when `ANTHROPIC_API_KEY` is unset — so **tests stay deterministic** and the
  no-key install story in the README survives.
- Optionally the *"causes we cannot verify"* panel: one bounded call listing plausible
  external causes with the data source that would test each. Visually separate,
  purely additive, and it answers "what if the real cause was never recorded?"
- Record model choice and cost-per-diagnosis in the Task 6 telemetry panel — the brief
  explicitly asks for that reasoning.

---

## Task 9 — `effect.py`: diff-in-diff + bootstrap CI

**Goal:** the −$410k headline currently ships with no interval and the README has to
apologise for it. `narrate.py:226` passes `effect=None`.

**Files:** `ledgerlens/effect.py` (new), `ledgerlens/narrate.py`

`EffectEstimate` (models.py:205), `config.BOOTSTRAP_ITERS` (2000) and `config.CI_LEVEL`
(0.95) all exist and are unused. The spec's own sketch is ~30 lines:

1. fit the pre-period relationship between the focal cohort and an unaffected control
   cohort (DACH-card, UK-sepa)
2. project through the incident window
3. bootstrap the residuals

Headline becomes **"−$410k (95% CI ±$Xk) vs counterfactual"** — materially stronger,
and it upgrades "materiality = statistical + business impact" from the brief.

**Test:** the true injected effect from `ground_truth.json` falls inside the CI; the
interval is not degenerate.

---

## Task 10 — Ingest `slack.json`

**Goal:** `data/slack.json` is generated by `gen_data._write_slack()` and read by
nothing. Easy heterogeneous-sources win.

**Files:** `ledgerlens/ledger/connectors.py`, `ledgerlens/store.py`

A deterministic keyword/regex lane turning the ops alert into a corroborating signal,
labelled **"unstructured source — inferred, verify"**. `ChangeEvent.extraction` already
distinguishes `deterministic` from inferred, and `app.py` already renders that as a
`🏷️ Inferred — verify` badge — so the UI work is zero. Closes the two-lane ingestion
loop the README already claims.

---

## Task 11 — `ambiguity.py`: the discriminating test

**Goal:** the design doc calls this the thing "no other team will have", and it is the
best answer to the brief's uncertainty requirement.

**Files:** `ledgerlens/ambiguity.py` (new), `ledgerlens/gen_data.py`,
`ledgerlens/pipeline.py`

`config.AMBIGUITY_EPSILON` (0.08) and the `DiscriminatingTest` model (models.py:232)
exist; `DiagnosisCard.open_question` is always `None`.

Minimal version: when the top-2 scores are within ε, diff the two blast radii, find a
slice where they predict different behaviour, run the query if the data can answer it,
otherwise emit the cheapest next test with an owner.

**Needs a generator scenario that actually produces a near-tie**, or it never appears
on camera. That dependency on `gen_data.py` is why this is last — same fragility risk
as Task 3.

---

## Task 12 — Submission package

**Files:** `.gitignore`, `README.md`, `requirements.txt`, `docs/`, `mockups/`

- **`.gitignore` `*.md` fix** (§0) — do this *first*, or the proposal silently never
  commits
- **`requirements.txt` / lockfile** — `uv pip compile`, so the 30-second install claim
  survives a judge's laptop
- **README requirement-map table** — a row per brief requirement → where it lives in
  the repo. Makes grading effortless; costs an hour
- **Screenshots / GIF** — `../mockups/` already has six rendered screens
  (`mock_1_dashboard_alert.png` … `mock_6_release_watch.png`) to mirror
- **Charts** (P2, if time): `plotly` is already a dependency and `app.py` has **zero**
  plots. Two earn their place — (1) focal metric time series with the frozen
  Theil–Sen baseline overlaid and the anomaly window shaded, the single most
  persuasive image this system can produce; (2) an attribution treemap above the
  dataframe
- **Watchtower landing** (P2, if time): the brief says "detects *and prioritises*". A
  list of all metrics scanned as-of the date, one row per flagged anomaly, click
  through to the diagnosis. Reframes the product from "tool you point" to "engine that
  surfaces"
- **Business proposal** — problem framing, target users, business case, phased roadmap
  (§10 of the redesign doc is already this), risks + mitigations (the README's honesty
  section is already this). Mostly assembly
- **Regenerate the "96 tests" claim** — README lines 42 and 170. Tasks 1–7 all add
  tests; the number must stay true
- **Demo video** — beats: pain → watchtower alert → drill-down finds
  DACH×Enterprise×SEPA → *linger on the decoy being rejected by the control that
  killed it* → CFO vs on-call from the same evidence → confirm click moves the prior →
  abstention + telemetry close: *"and when it doesn't know, it says so — for $0.00 per
  diagnosis."*
- **Push.** Nothing since Aug 16 is on the remote.

---

## Cross-cutting notes

**The `load()` cache key.** `app.py`'s `@st.cache_resource` keys on
`(metric, as_of_iso)`. Tasks 2, 4, 5 and 7 all add inputs that change the rendered
card. Every one must join that key, or the demo shows a stale card at the worst
possible moment. Consider fixing the signature once, now, rather than four times.

**`gen_data.py` is the fragile one.** Tasks 3 and 11 both touch it. It is seeded and
`test_pipeline.py` asserts the exact injected incident and the exact rejected decoy.
Regenerate and run the full suite after *any* change there, and never let a new metric
perturb the two existing series.

**Test count is a claim.** The README states 96 in two places. It is currently true.
Keep it true.
