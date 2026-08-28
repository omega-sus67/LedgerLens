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

## Current state (as of 2026-08-28)

- Deterministic core is done and stable: **126 tests passing**, decoy-rejection demo
  works end-to-end, README's claims verified against the code.
- Confirmed via a genuine cold clone (`git clone` into `/tmp`, fresh venv, README's
  documented install steps only) that `gen_data.py` -> `pytest` -> `pipeline.py`
  reproduce the full diagnosis card with zero data files at checkout. `data/*` is
  gitignored on purpose -- it's deterministic generator output (`SEED = 20260815`)
  -- and that design is correct, not a bug.
- **`taskflow/taskflow.md` is the live plan**, written 2026-08-28 against the repo as
  it stands. It supersedes `improvements.md`, whose Aug 26-27 schedule did not land.
  Twelve tasks, ordered so each unblocks the next; items 1-7 are literal rows on the
  judges' Minimum Prototype Expectations list and must never be cut.
- **Nothing since 2026-08-16 is pushed.** All of the contract work is uncommitted
  local state.

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
- `tests/test_contracts.py` (new, 26 tests) + 4 added to `tests/test_app.py`. The
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

**Next up: task 2 (personas + `Action` reshape).** When it lands, fix `app.py`'s
`@st.cache_resource` key ONCE -- it currently keys on `(metric, as_of_iso)` only, and
tasks 2, 4, 5 and 7 each add an input that changes the rendered card. Task 1 needed no
cache work (the expander renders outside `load()`), so this is still unpaid.

## Conventions this repo uses (learned, not to be reinvented)

- **Every number traces to a query.** `Store.q()` is the only path to the
  database; it hashes SQL+params into a `query_id` and logs it. Any new feature
  that surfaces a number to the UI should route through it — that's the
  anti-hallucination mechanism the whole pitch rests on.
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
- **Tests before claims.** Any refactor of `anomaly.py`/`hypothesis.py`/
  `controls.py` should be checked against a before/after characterization
  snapshot in addition to `pytest -q`, because the test suite doesn't exercise
  every metric/as_of combination the live UI can reach (e.g. `new_logo_bookings`
  detection has no dedicated test file).

## Deadline context

Submission: **2026-08-30**. The schedule is `taskflow/taskflow.md`'s task order, not
`improvements.md`'s (that one assumed Aug 26-27 work that did not land). Task 1 is done;
2-7 are the remaining checklist rows and are non-negotiable, since a missing checklist
row is a zero rather than a deduction. Cut line if behind: drop task 11 (ambiguity),
then 10 (Slack ingest), then 9 (effect CI), then 8 (real LLM call).

`gen_data.py` is the fragile one -- tasks 3 and 11 both touch it, it is seeded, and
`test_pipeline.py` asserts the exact injected incident and the exact rejected decoy.
Regenerate and run the full suite after any change there.
