# CLAUDE.md

Working notes for Claude sessions on LedgerLens. Read this before making changes;
update it after making changes. This file tracks **project state and decisions**,
not a line-by-line diff history — `git log` is authoritative for that.

## What this is

Root-cause analysis engine for the Accenture Innovation Challenge 2026 (Track 3,
BusinessIntelligence.ai). Round 1 (concept deck + video) is submitted. Round 2
(working prototype) is due **2026-08-30** and needs: a working prototype, a
detailed business proposal, and a public GitHub repo with demo video + README.

Read [README.md](README.md) first for what the system actually does and the honest
scope of its claims — it is the canonical description and is kept accurate
deliberately; don't let this file duplicate or drift from it.

## Current state (as of 2026-08-30)

- Deterministic core is done and stable: **293 tests passing**, decoy-rejection demo
  works end-to-end, README's claims verified against the code.
- **Tasks 1, 2, 3, 4, 6 and 7 are done** (KPI semantic contract; personas + `Action`
  reshape; third KPI with sparse history; role-based entitlement; telemetry panel;
  reachable abstention).
  Rationale for each lives in `docs/contracts_decisions.md`,
  `docs/persona_decisions.md`, `docs/sparse_kpi_decisions.md`,
  `docs/roles_decisions.md`, `docs/telemetry_decisions.md` and
  `docs/abstention_decisions.md`. 1-3 are merged to `main`; **4, 6 and 7 are stacked
  and unmerged**: `task-4-entitlement` -> `task-6-telemetry` -> `task-7-abstention`.
- **ALL TEN Minimum Prototype Expectation rows close.** Task 6 closed the last two
  (row 9, LLM vs non-LLM breakdown; row 10, runtime telemetry); task 7 hardened row 5
  by making abstention reachable from the UI. **Only task 12 (submission package)
  remains, and it is a deliverable rather than a feature.**
- Confirmed via a genuine cold clone (`git clone` into `/tmp`, fresh venv, README's
  documented install steps only) that `gen_data.py` -> `pytest` -> `pipeline.py`
  reproduce the full diagnosis card with zero data files at checkout. `data/*` is
  gitignored on purpose -- it's deterministic generator output (`SEED = 20260815`)
  -- and that design is correct, not a bug.
- **`taskflow/taskflow.md` is the live plan**, rewritten 2026-08-29 and cut to
  essentials. The original twelve tasks were not achievable in the time left; what
  remains is 4 (role-based entitlement), 6 (telemetry panel), 7 (abstention demo path)
  and 12 (submission package), plus conditional 5. Tasks 9-11 remain cut deliberately
  and are named in the file with the reason. **Task 8 was un-cut and built**: the
  challenge is an AI challenge and the repo had no LLM in it. Seven of the ten Minimum Prototype
  Expectations already close; tasks 4 and 6 close the remaining three rows.
- **Everything through task 3 is pushed to `origin/main`.** The stacked branches
  `task-2-personas` and `task-3-sparse-kpi` were fast-forwarded into `main`.
- **`tests/test_docs.py` guards the README's own claims.** The test count in
  `README.md`, the completeness of every `config.PROVIDERS` row, and the README's
  naming of the default model and its API-key env var are assertions, not prose.
  It no longer pins a vendor string -- task 8 replaced that with seam checks. If it
  goes red, update the document -- do not delete the test. **It fires on every task that
  adds tests**, so update `README.md`'s count in the SAME commit rather than at the end
  of a branch, or every intermediate commit is red.

## Done: task 1 -- the KPI semantic contract

`contracts.py` is no longer dead metadata. It is read by the engine, rendered by the
UI, and guarded by tests. Closes three checklist rows at once (the contract itself,
"different grains / refresh cadences", and "evidence: freshness + lineage").

**Full rationale lives in [docs/contracts_decisions.md](docs/contracts_decisions.md)** --
every model, field, and decision, end to end. Read that before changing `contracts.py`;
this section is only the state summary.

- `ledgerlens/contracts.py` -- `KpiContract`, `Thresholds`, `LineageStep`, `AccessRule`,
  contracts for both KPIs. `scan_for_onset()`/`drill()` read `contracts.thresholds()`.
- **`related_event_types` split from `anticipated_event_types`.** The old single list
  claimed `vendor_incident`/`policy_change`/`external`, none of which any connector
  emits. Now: what the ledger carries vs. known drivers with no feed, each tested in
  its own direction. The second list feeds the abstention story (task 7) for free.
- **`contracts.freshness(store, metric, as_of)`** -- measured freshness per lineage
  step, beside the declared cadence. Issued through `store.q()` so each number carries
  a replayable `query_id`. **Bounded by `as_of`, not the wall clock and not an
  unbounded `max(date)`**: the generator writes through `GEN_END = 2026-08-31` while
  the demo is pinned at `DEFAULT_AS_OF = 2026-08-17`, so the naive version prints a
  *negative* lag on stage. `test_freshness_is_never_negative` is the regression test.
  This is why `store.max_date()` is NOT reused -- no as-of bound, and it bypasses `q()`.
- `app.py` -- collapsed "📜 Contract" expander (definition, calculation SQL, drivers,
  unconnected event types, thresholds, lineage+freshness, access policy). Sidebar
  thresholds AND the headline "Robust z" caption now read `contracts.thresholds(metric)`
  instead of `config.*`, so the contract is visibly in force rather than decorative.
- `tests/test_contracts.py` (new; 26 tests at task 1, 29 after task 3 added the ratio
  KPI) + 4 added to `tests/test_app.py`. The
  important one is `test_threshold_defaults_are_exactly_the_global_constants`: it
  guards the invariant the already-landed `anomaly.py` refactor rests on, which
  nothing checked before. Also a `calculation_sql` round-trip against `Store.series()`,
  and both ledger-drift directions against `gen_data.py`.
- **`.gitignore` `*.md` fix pulled forward from task 12** (`!README.md`,
  `!taskflow/*.md`, `!docs/*.md`) -- without it every new markdown file, including the
  taskflow and the business proposal, is silently ignored. `improvements.md` stays
  ignored, which is correct.

**Deliberately NOT done in task 1:** freshness does not go on `DiagnosisCard`, so
`models.py` and `pipeline.py` are untouched and `test_pipeline.py`'s acceptance test is
not at risk. Provenance is preserved by the `query_id` on each `SourceFreshness`.

**Cache-key debt: PAID in task 4.** `load_payload` now keys on
`(metric, as_of_iso, cohort_key, window_key, role_key)`. Persona stays OUT of the key on
purpose -- it lives below the payload boundary and changes only prose. **Task 7's
`drop_sources` and task 5's feedback are the same shape and belong in this signature**,
not in a separate patch; the docstring on `load_payload` says so.

## Done: task 4 -- role-based entitlement

Closes the last uncovered Minimum Prototype Expectation row (7, role-based security).
**Full rationale in [docs/roles_decisions.md](docs/roles_decisions.md)** -- read it
before touching `AccessRule`, `pipeline._visible_dims`, or the cache key.

- **Enforced in exactly one place:** the `dims` list handed to `anomaly.drill()`.
  `hypothesis`, `controls` and `narrate` stay unaware roles exist.
- **`role` enters ABOVE the payload boundary; persona stays below it.** Role changes
  which cuts are drilled, so it changes the focal cohort and therefore the numbers.
  Persona never changes a number. Do not conflate them -- that distinction is the whole
  reason `diagnose()` and `narrate()` are separate functions.
- **The growth card genuinely differs:** focal `DACH - Enterprise - A` at -$207,545,
  against the analyst's `DACH - Enterprise - sepa` at -$416,144. That is correct, and the
  banner naming policy `fin.rail_detail` is what makes it read as governance rather than
  breakage. **Never ship the dim-hiding without the banner.**
- **Ranked ORDER is identical across roles; scores are NOT** (0.700 vs 0.627), because
  `hypothesis.rank` scores against the focal cohort and the focal moved. Assert order,
  never scores -- `test_redaction_does_not_reorder_the_candidates` has the reasoning.
- **A redaction is not an `EvidenceStep`** -- that model requires a `query_id` and there
  is no query behind a policy decision. `Redaction` is its own model.
- **The banner does not count hidden slices.** Computing that count means running the
  unrestricted drill, i.e. producing the answer the reader is not entitled to.
- **The engine uses the LENIENT contract lookup** (`contracts.CONTRACTS.get`), matching
  `contracts.thresholds()`. `contracts.get` raises and belongs to the UI only.
- **Known gap, documented not fixed:** manual cohort selection bypasses the drill
  chokepoint and is not entitlement-checked. Unreachable today (only sparse-history KPIs
  use that path, and none declare an `AccessRule`). See `roles_decisions.md` D7.
- **Demo consequence:** "same evidence, four audiences, identical query ids" is now false
  for `growth` and must be re-scripted. It holds for analyst/cfo/oncall.
  `tests/test_narrate_personas.py` still passes -- it renders one role-free payload four
  ways, which is still the meaningful invariant.

## Done: task 6 -- the telemetry panel

Closes MPE rows 9 and 10, which takes the checklist to ten of ten.
**Full rationale in [docs/telemetry_decisions.md](docs/telemetry_decisions.md).**

- **"Queries" is THREE numbers, and merging them understates the work ~6x.**
  `queries_executed` (86 cold) is what the diagnosis cost; `queries_on_card` (19) is
  what a reader can audit; `queries_cached` (39) is work avoided. **Never add a field
  called `queries`.** Metadata lookups (`dim_universe`, `events`) are counted in none of
  them -- no user-facing number, so no `query_id`.
- **The counter lives on `Store`**, because only `q()` knows what was a cache hit.
  `stats_snapshot()` returns a COPY; `diagnose()` subtracts before from after, so a
  long-lived Store reports per-diagnosis rather than since-boot.
- **`stage_ms` keys reflect the path taken** -- the manual-window branch reports
  `{measure, symptoms, rank, seasonal}`, not five keys padded with 0.0. A padded zero
  reads as "instant"; an absent key reads as "not applicable".
- **Never assert a duration.** Cold vs warm is 2.6x and the session-scoped `store`
  fixture's warmth is test-ORDER dependent. Assert structure and zero.
  `test_runs_within_the_latency_budget`'s 5.0s bound stays as it is -- do not tighten it
  to flatter telemetry.
- **`total_ms` includes narration** because the panel lists narration as a stage.
  Otherwise the share column sums past 100%, which is the kind of small error that makes
  a reader distrust every other number.
- **`_Stopwatch.time` uses try/FINALLY.** The timing is recorded even when a stage
  raises, and the exception still propagates. Do not convert it to `except`.

## Done: task 7 -- reachable abstention

`_no_cause_card` was always well written and always unreachable without editing source.
A sidebar switch now simulates the deploy connector never having been wired up.
**Full rationale in [docs/abstention_decisions.md](docs/abstention_decisions.md).**

- **The filter is at CANDIDATE GENERATION, not a score penalty.** An unconnected system
  produces no rows, not a low-scoring candidate. Penalising later would model "we saw it
  and dismissed it", and would leave `deploy_sepa_v214` on the card as a rejected
  hypothesis -- exactly the wrong story.
- **Fixed a real bug: `_no_cause_card` hardcoded its connectivity prose.** With github
  dropped it printed "Connected sources: deploys (github)..." -- the card contradicting
  the demo, in the branch whose whole purpose is honesty. Connectivity is now read off
  `contract.lineage`; the "no feed exists" list off `contract.anticipated_event_types`.
  Only the DISPLAY labels (`SOURCE_LABEL`) are local. **Never retype a connectivity
  claim into narrate.py.**
- **The decoy stays rejected when competition is removed** (0.322, killed by its own
  segment-sibling control). That is load-bearing: a decoy promoted the moment rivals
  vanish would mean the control was never doing the work.
- **`drop_sources` is the THIRD cache-key input** after cohort/window and role. The
  signature now scales; task 5's feedback would be the fourth.
- **A system that shows less must say why.** Same principle as task 4's redaction
  banner: the toggle is labelled, captioned while active, and the card names the feed it
  is missing.

## Done: task 8 -- the investigator lane (the AI)

The repo had **zero LLM calls** on an AI challenge. Not an oversight in the design --
`businessintelligence-ai-redesign.md` sec 4.9 specifies the lane and nothing built it,
leaving `config.MODEL`, `LLM_TEST_BUDGET`, `Telemetry.llm_*`, `generated_by`,
`ProposedTest` and `UnverifiedHypothesis` as sockets with nothing plugged in.
**Full rationale in [docs/ai_decisions.md](docs/ai_decisions.md)** -- read it before
touching `llm.py`, `investigator.py`, `config.PROVIDERS` or the `investigate` flag.

- **THE invariant: the LLM cannot change a rank.** Enforced in three places, not by
  convention: proposed checks are built with `decisive=False` (the field
  `controls.score_n` reads), they are never passed to `score_n`, and the lane runs
  AFTER `hypothesis.rank`. `test_the_lane_cannot_change_a_single_score` asserts scores,
  not order -- order is the weaker claim.
- **Provider-agnostic, Gemini Flash by default.** `config.PROVIDERS` is the ONLY place
  a vendor is named; `llm.py` has one adapter per row. `LEDGERLENS_LLM_PROVIDER=anthropic`
  switches vendor with no source change. **The `Provider` protocol has exactly one
  method** and there is a test that keeps it that way -- a second method would describe
  one vendor's feature and the investigator would start branching on vendor.
- **Wire schemas are hand-written, NOT `model_json_schema()`.** Pydantic emits
  `$defs`/`$ref`, which Gemini's `responseSchema` rejects outright. Two tests guard it.
- **Gemini transport is raw REST over httpx**, deliberately: no new dependency, and an
  SDK abstraction leaks its vendor's concepts into the seam. `httpx` is now a DIRECT
  dependency and is in the README install line.
- **The numbers guard is strict on purpose.** Any numeric token in LLM prose that is
  not in the corpus discards the whole narration for the template version. No tolerance
  window -- a tolerance window is a range inside which a wrong number is permitted.
  Rejections are shown on the page as the guard working.
- **Validation rejections are COUNTED and displayed** ("4 accepted, 2 rejected"). A
  validator that never reports catching anything is indistinguishable from one that is
  not running.
- **Real bug found and fixed: narration must not bill against the cached payload.**
  `load_payload` is `@st.cache_resource`; recording narration into `payload.llm_budget`
  made every re-render increment the same object, so the cost climbed as the reader
  clicked. `narrate()` uses a fresh budget and `Budget.plus` sums immutably. See D11.
- **Site 1 (the LLM event normalizer) is CUT, not merely unbuilt.** It is the only one
  of the four spec'd sites that is not additive -- it multiplies a score by an
  LLM-emitted confidence, which puts a model on the ranking path. Reasoning in D2;
  the README's "Not built" section says so too.
- **`tests/test_docs.py` no longer pins a vendor string.** Pinning `claude-sonnet-5`
  would re-hardcode the coupling `PROVIDERS` exists to remove, so the guard moved to
  the seam: every provider row must be complete, every row must have a transport, and
  the README must name the default model and its env var.
- Test count **229 -> 293**. `test_investigator.py` (36) and `test_llm.py` (19) are new;
  8 added to `test_app.py`, including a check that the AI toggle does not displace the
  source-drop checkbox that two other tests address BY INDEX.

## Conventions this repo uses (learned, not to be reinvented)

- **Every number traces to a query.** `Store.q()` is the only path to the
  database; it hashes SQL+params into a `query_id` and logs it. Any new feature
  that surfaces a number to the UI should route through it — that's the
  anti-hallucination mechanism the whole pitch rests on.
- **There are exactly TWO deliberate exceptions to that rule**, and both are facts
  about the PROCESS rather than the data: the telemetry panel (latency) and the
  redaction notice (policy). Both say so on screen rather than leaving a gap to be
  noticed. **A third exception should have to make the argument again** -- two is a
  considered boundary, three is a habit.
- **`config.py` holds only global defaults now that `contracts.py` exists.**
  Per-KPI alerting behavior belongs in a `KpiContract`; genuinely global pipeline
  parameters (e.g. `CONTRIBUTION_FLOOR`, `MAX_DRILL_DEPTH`) stay in `config.py`.
  Don't blur that line — it's what makes the contract meaningful rather than
  decorative.
- **`SPEC-GAP:` comments** in `config.py` mark deliberate, reasoned deviations from
  `IMPLEMENTATION_SPEC.md`. Read them before "fixing" a threshold that looks
  arbitrary — most of them exist to make a specific acceptance test deterministic.
- **`SEED = 20260815`** throughout; the generator solves scaling constants in
  closed form against target window sums rather than hand-tuned RNG. Don't
  reseed casually — several tests assert exact values downstream of it.
- **Two baselines, never conflate them.** `scan_for_onset` (trailing, causal,
  cheap — for finding *where*) vs `evaluate`'s Theil–Sen pre-window fit (frozen,
  for measuring *how big*). Using the trailing one to measure is a documented
  real bug (`anomaly.py`'s module docstring), not a style choice.
- **On this machine**, a ROS install pollutes `PYTHONPATH`. Prefix Python
  invocations with `env -u PYTHONPATH -u VIRTUAL_ENV` or `pytest`/imports can fail
  mysteriously (e.g. `yaml` import errors) — this is also why `contracts.py` uses
  Pydantic instead of a YAML file, on purpose.
- **`gen_data.py` uses ONE sequential RNG stream.** Any new generated series MUST
  take its own `np.random.default_rng(SEED_*)`, or every downstream draw shifts and
  the acceptance numbers drift inside their band -- green tests, wrong demo.
  `tests/test_sparse_kpi.py`'s fingerprint tests enforce this. If they fail, fix the
  generator, NEVER update the hash.
- **A KPI's aggregation lives in its contract, not in the engine.** `agg="sum"` vs
  `agg="ratio"` and `source_metrics` (the physical `metric_name` rows behind a KPI)
  are read by `Store.series`, `Store.cohort_rows` and `contracts.freshness`. Adding a
  ratio KPI without wiring all three silently zeroes the C component for that KPI.
- **Tests before claims.** Any refactor of `anomaly.py`/`hypothesis.py`/
  `controls.py` should be checked against a before/after characterization
  snapshot in addition to `pytest -q`, because the test suite doesn't exercise
  every metric/as_of combination the live UI can reach (e.g. `new_logo_bookings`
  detection has no dedicated test file).

## Deadline context

Submission: **2026-08-30**. The schedule is `taskflow/taskflow.md`'s task order. Tasks
1-4, 6 and 7 are done (4, 6, 7 unmerged and stacked). **All ten checklist rows close.**
Task 12
(submission package) is a *deliverable*, not a feature -- never cut it. Cut line if
behind: drop task 5 (learning loop), then the P2 items inside 12. Tasks 8-11 are already
cut.

`gen_data.py` is the fragile one -- tasks 3 and 11 both touch it, it is seeded, and
`test_pipeline.py` asserts the exact injected incident and the exact rejected decoy.
Regenerate and run the full suite after any change there.
