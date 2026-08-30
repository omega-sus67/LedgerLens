# LedgerLens — Study Guide

**A sequential path through this repository.** The [`README.md`](README.md) is organised by
*claim* and [`docs/README.md`](docs/README.md) is organised by *topic*. This file is
organised by **reading order**: what to open first, what to run at each point, and what you
should be able to answer before moving on.

Seven phases. Each one names who can stop there, so you can read exactly as deep as your
purpose requires:

| Phase | What you get | Time | Stop here if you are… |
|---|---|---|---|
| [0 — Orientation](#phase-0--orientation) | the vocabulary and the honest scope | 10 min | deciding whether this is interesting |
| [1 — See it run](#phase-1--see-it-run) | the demo, in your own terminal | 20 min | evaluating the submission, not the code |
| [2 — The architecture](#phase-2--the-architecture-in-pipeline-order) | the pipeline, stage by stage against source | 45 min | reviewing the design |
| [3 — The decision records](#phase-3--the-decision-records-in-build-order) | why every subsystem is the way it is | 2–3 h | about to change the code |
| [4 — How it was built](#phase-4--how-it-was-built) | the plans, the spec, the deviations | 1 h | curious about process; optional |
| [5 — Changing it safely](#phase-5--changing-it-safely) | the conventions and the tests that enforce them | 30 min | writing a patch |
| [6 — The submission](#phase-6--the-submission) | proposal, checklist coverage, rebuild steps | 20 min | packaging or judging |

Two conventions used throughout:

- **§ N** refers to a numbered section heading inside the linked document.
- Where a document and this guide disagree, **the document wins**. This file sequences and
  connects; it deliberately does not restate. Numbers in particular live in
  [`README.md`](README.md), and [`tests/test_docs.py`](tests/test_docs.py) guards them there.

---

## Phase 0 — Orientation

**Time:** 10 minutes. **Assumes:** nothing.

### Read, in this order

1. **[`docs/how_it_works.md`](docs/how_it_works.md)** — the whole system from zero, no
   analytics background assumed. Read it end to end. Its **§2 "The eight words you need"**
   is the vocabulary every other document in this repo presumes you already have; the
   **omission rule** at the end of §2 (*a dimension you do not mention means all of them*)
   is the single idea the entire scoring system turns on.
2. **[`README.md`](README.md)** — just the top, through the section *"Read this first: what
   this does and does not claim."* That table is the honest scope: what each of the five
   score components T, C, D, N, P really measures, and what it explicitly does **not** mean.

### You can now answer

- What is a **blast radius**, and why does it make relevance a *set intersection* rather
  than a graph traversal?
- Why does this system refuse to claim **causation**, and what does it claim instead?
- What does an omitted dimension in a blast radius mean — and why does that make the
  marketing campaign's region-only radius a *weakness* rather than a strength?
- Which of T, C, D, N, P is uninformative for this particular incident, and why is that
  stated on the card rather than hidden?

> **Stop here** if you only needed to know what the product claims.

---

## Phase 1 — See it run

**Time:** 20 minutes. **Assumes:** Phase 0's vocabulary.

### Run

Straight from [`README.md` § "Run it"](README.md) — these steps are verified against a cold
clone:

```bash
uv venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt

.venv/bin/python -m ledgerlens.gen_data    # writes data/*.parquet, *.json, ground_truth.json
.venv/bin/python -m pytest -q              # the count README.md claims
.venv/bin/python -m ledgerlens.pipeline    # prints the diagnosis card to stdout
.venv/bin/python -m streamlit run app.py   # the analyst UI
```

Three things that trip up a first run:

- **`data/` is empty at checkout, and that is correct.** It is deterministic generator
  output (`SEED = 20260815` in [`config.py`](config.py)) and is gitignored on purpose — the
  cold-clone install story is real rather than claimed. `gen_data` rebuilds all of it.
- **No API key is required.** Everything on the ranking path is deterministic Python and
  SQL. The AI investigator is a separate, optional lane — Phase 3, record 7.
- **On a machine with ROS installed**, prefix commands with
  `env -u PYTHONPATH -u VIRTUAL_ENV` or imports fail mysteriously.

### Then read

**[`docs/demo_script.md`](docs/demo_script.md)** — nine beats, each mapping onto a specific
part of the running UI, so it doubles as a guided tour. Follow it with the app open. If you
are not running the app, [`docs/screenshots/`](docs/screenshots) has the same beats captured.

The UI itself is one file, [`app.py`](app.py); its sidebar is where every interesting
behaviour is switched on.

### You can now answer

- Where on the card does the decoy `campaign_dach_cut` get **rejected**, and what kills it?
- Which **two** sidebar controls produce the system's two different refusals — one that
  declines to *detect*, one that declines to *explain*?
- What does the ⏱ Telemetry expander report, and which two of its numbers must never be
  merged into one called "queries"?
- What changes on the card when you switch the persona selector to **Growth Marketing** —
  and why does a *number* change, not just the prose?

> **Stop here** if you are evaluating the submission rather than the code.

---

## Phase 2 — The architecture, in pipeline order

**Time:** 45 minutes. **Assumes:** Phases 0–1.

Read [`docs/how_it_works.md` §5 "The six stages"](docs/how_it_works.md) once more with the
source open. Then walk the pipeline diagram in [`README.md` § "Pipeline"](README.md) left to
right. Each stage has exactly one source file:

| Stage | Source | Read alongside |
|---|---|---|
| KPI semantics — definitions, thresholds, lineage, access | [`ledgerlens/contracts.py`](ledgerlens/contracts.py) | [`docs/contracts_decisions.md`](docs/contracts_decisions.md) |
| Store + query registry | [`ledgerlens/store.py`](ledgerlens/store.py) | `how_it_works.md` §8 |
| Synthetic generator (writes the ground truth) | [`ledgerlens/gen_data.py`](ledgerlens/gen_data.py) | `README.md` § "What the demo shows" |
| Detection, measurement, drill-down, BH | [`ledgerlens/anomaly.py`](ledgerlens/anomaly.py) | `README.md` § "Design notes worth knowing" |
| Change ledger — typed events + blast radius | [`ledgerlens/ledger/connectors.py`](ledgerlens/ledger/connectors.py) | `README.md` § "The core primitive" |
| Symptom stream — ticket clustering | [`ledgerlens/ledger/symptoms.py`](ledgerlens/ledger/symptoms.py) | `how_it_works.md` §4 |
| Candidates + five-component scoring | [`ledgerlens/hypothesis.py`](ledgerlens/hypothesis.py) | `how_it_works.md` §6 |
| Negative control generation and evaluation | [`ledgerlens/controls.py`](ledgerlens/controls.py) | `how_it_works.md` §7 |
| Learned prior | [`ledgerlens/learning.py`](ledgerlens/learning.py) | [`docs/learning_decisions.md`](docs/learning_decisions.md) |
| Narration — template + guarded LLM | [`ledgerlens/narrate.py`](ledgerlens/narrate.py) | [`docs/persona_decisions.md`](docs/persona_decisions.md) |
| Provider seam and the LLM lane | [`ledgerlens/llm.py`](ledgerlens/llm.py), [`ledgerlens/investigator.py`](ledgerlens/investigator.py) | [`docs/ai_decisions.md`](docs/ai_decisions.md) |
| Orchestration | [`ledgerlens/pipeline.py`](ledgerlens/pipeline.py) | the `diagnose()` / `narrate()` split |
| Pydantic contracts and the cohort algebra | [`ledgerlens/models.py`](ledgerlens/models.py) | — |
| Global defaults, weights, `SEED` | [`config.py`](config.py) | its `# SPEC-GAP:` comments |
| The UI | [`app.py`](app.py) | — |

### The one invariant to carry into Phase 3

**Every number traces to a query.** `Store.q()` is the only path to the database: it hashes
the SQL plus its bound parameters into a `query_id`, logs the statement and a result
preview, and hands both back. There are exactly **two** deliberate exceptions, and both are
facts about the *process* rather than the data — the telemetry panel (latency) and the
redaction notice (policy). Both say so on screen.

Almost every decision record in Phase 3 is downstream of that rule. Read
[`docs/how_it_works.md` §8](docs/how_it_works.md) before continuing if it is not yet solid.

### You can now answer

- Why are there **two different baselines** in [`anomaly.py`](ledgerlens/anomaly.py), and
  what specific error do you get from using the trailing one to *measure* rather than to
  *find*?
- Why must the pre-window exclude the anomaly window?
- Why is detection **advisory rather than gating** — and what does that turn every
  detection blind spot into?
- Where do symptoms (support tickets) enter the score? (Trick question — read
  `README.md` § "Design notes".)

---

## Phase 3 — The decision records, in build order

**Time:** 2–3 hours. **Assumes:** Phase 2.

This is the heart of the repo. Eight records, one per subsystem: each says what was built,
what was deliberately *not* built, and the reasoning behind every choice a future reader
might otherwise undo.

**Read them in the order below, not the order [`docs/README.md`](docs/README.md) lists
them.** That file is a topical index and is alphabetical-ish; this is the order the
subsystems were actually built, and later records lean on earlier ones — record 6's
`drop_sources` is explicitly *"the third cache-key input after record 4's role"*, and
record 7's cost accounting is only legible once record 5 has defined the panel it appears in.

### 1. [`docs/contracts_decisions.md`](docs/contracts_decisions.md) — the KPI semantic contract

Guards [`ledgerlens/contracts.py`](ledgerlens/contracts.py). Definitions, calculation SQL,
drivers, thresholds, lineage and access policy, as code rather than metadata.
**The decision a reader will otherwise undo:** `freshness()` is bounded by `as_of`, not by
the wall clock and not by an unbounded `max(date)` — the generator writes past the demo's
pinned as-of date, so the naive version prints a *negative* lag on stage (§10).
Also: `related_event_types` vs `anticipated_event_types` (§9) — the second list is what
makes the abstention story possible at all.

### 2. [`docs/persona_decisions.md`](docs/persona_decisions.md) — four personas, one computation

Guards [`ledgerlens/personas.py`](ledgerlens/personas.py) and
[`ledgerlens/narrate.py`](ledgerlens/narrate.py).
**The central decision:** persona sits **downstream of every `Store.q()` call** (§3), so it
*cannot* reach a query — which is why `diagnose()` and `narrate()` are separate functions.
Then: levers and decision rights made mechanical (§5–6), `show_event_ids` governing action
text and not merely prose (§7), and the brief's seven-link `Action` chain field by field (§8).
§13 shows you how to verify the claim from a shell.

### 3. [`docs/sparse_kpi_decisions.md`](docs/sparse_kpi_decisions.md) — the KPI that declines to detect

Guards the third KPI, `payment_success_rate`, and the ratio path through
[`ledgerlens/store.py`](ledgerlens/store.py).
Two separate problems in one KPI: it is **too young to detect on** (declining is not the
same as failing), and it is a **rate**, which is not additive (§3).
**The decision a reader will otherwise undo:** the generator must take its own RNG stream
(§5). `gen_data.py` draws from one sequential stream, so a new series on the shared stream
shifts every downstream value — green tests, wrong demo.

### 4. [`docs/roles_decisions.md`](docs/roles_decisions.md) — entitlement that names itself

Guards `AccessRule` and `pipeline._visible_dims`.
**The distinction that matters:** role enters **above** the payload boundary and therefore
*does* change numbers, where persona enters below it and never does. Do not conflate them.
Also: a `Redaction` is not an `EvidenceStep` (there is no query behind a policy decision),
the banner deliberately does **not** count the slices it hides, and ranked *order* is
identical across roles while *scores* are not — assert order, never scores (§4).
§7 names the gaps honestly, including the one bypass that is unreachable today.

### 5. [`docs/telemetry_decisions.md`](docs/telemetry_decisions.md) — honest cost accounting

Guards the ⏱ panel in [`app.py`](app.py) and the counter on `Store`.
**The decision a reader will otherwise undo:** "queries" is **three numbers**, and merging
them understates the work roughly fourfold in the one panel whose entire job is honesty.
Never add a field called `queries`. Also: never assert a *duration* in a test — cold and
warm differ by more than 2×, so assert structure and zero instead.

### 6. [`docs/abstention_decisions.md`](docs/abstention_decisions.md) — refusing, reachably

Guards the `drop_sources` path and `narrate._no_cause_card`.
**The decision a reader will otherwise undo:** the filter lives at **candidate generation**,
not as a score penalty. An unconnected system produces no rows, not a low-scoring
candidate; penalising later would model *"we saw it and dismissed it"* and would leave the
true cause on the card as a rejected hypothesis — exactly the wrong story.
Also: a system that shows less must say why, and the connectivity list is read off the
contract's lineage rather than retyped into the narrator.

### 7. [`docs/ai_decisions.md`](docs/ai_decisions.md) — the investigator lane

Guards [`ledgerlens/llm.py`](ledgerlens/llm.py),
[`ledgerlens/investigator.py`](ledgerlens/investigator.py) and `config.PROVIDERS`.
The longest record, and the one to read most carefully.
**THE invariant: the LLM cannot change a rank** — enforced in three separate places rather
than by convention (§3). Then: the provider seam with exactly one method on the `Provider`
protocol; hand-written wire schemas rather than `model_json_schema()`; the strict numbers
guard with **no** tolerance window; and validation rejections being *counted and displayed*,
because a validator that never reports catching anything is indistinguishable from one that
is not running.
**§3 D2** explains why the fourth spec'd call site — the LLM event normalizer — is
deliberately **cut** rather than merely unbuilt: it is the only one that is not additive.

### 8. [`docs/learning_decisions.md`](docs/learning_decisions.md) — a prior you can delete

Guards [`ledgerlens/learning.py`](ledgerlens/learning.py).
A Beta–Bernoulli posterior re-counted from rows on every diagnosis, so there is no model
state — deleting a row puts the prior back exactly where it was.
**Two things a reader will otherwise break:** `record()` must invalidate the cached count
*by label* (a blanket cache clear corrupts the telemetry panel's cold/warm split), and P's
weight must never rise above `0.05` — at that bound a saturated prior provably cannot lift a
candidate over the score floor or rescue one a control killed, and that is what makes the
loop safe to expose to users.

### You can now answer

- Why is **persona** absent from the `load_payload` cache key while **role** is present?
- Why is a `Redaction` not an `EvidenceStep`?
- What are the exactly two numbers on screen that carry no `query_id`, and what do they have
  in common?
- Name the three independent mechanisms that stop the LLM from changing a rank.
- Why would raising P's weight to 0.2 be unsafe?
- Why does the abstention branch filter at candidate generation instead of penalising a score?

---

## Phase 4 — How it was built

**Time:** 1 hour. **Optional** — skip to Phase 5 if you only need to work on the code.

### The plans

[`docs/taskflow/taskflow.md`](docs/taskflow/taskflow.md) is the live plan: the task order,
what closes which checklist row, and — more usefully — the **cut list with a reason per cut**.
The per-task implementation plans follow:

- [`docs/taskflow/task_persona.md`](docs/taskflow/task_persona.md) — personas and the `Action` reshape
- [`docs/taskflow/task_sparse_kpi.md`](docs/taskflow/task_sparse_kpi.md) — the third KPI
- [`docs/taskflow/roles_tasks.md`](docs/taskflow/roles_tasks.md) — role-based entitlement
- [`docs/taskflow/telemetry_tasks.md`](docs/taskflow/telemetry_tasks.md) — the telemetry panel

> **Where a plan and a decision record disagree, the decision record wins.** The plans are
> kept rather than deleted precisely because several of them record errors that were only
> caught *during* implementation — each such plan opens with the correction. They show what
> the corrected reasoning in Phase 3 was corrected *against*.

### The background

- [`docs/design/IMPLEMENTATION_SPEC.md`](docs/design/IMPLEMENTATION_SPEC.md) — the build
  contract the prototype was written against. Every deliberate departure from it is marked
  `# SPEC-GAP:` **at the point of departure in the source**, with its reason. Grep for it:
  ```bash
  grep -rn 'SPEC-GAP' config.py ledgerlens/
  ```
- [`docs/design/businessintelligence-ai-redesign.md`](docs/design/businessintelligence-ai-redesign.md)
  — the architecture rationale: why a change ledger and a set intersection rather than a
  graph database, a vector store and an agent framework. §4.9 specifies the investigator
  lane that Phase 3's record 7 eventually built.

### You can now answer

- Which tasks were cut, and what is the stated reason each one is safe to cut?
- What is `# SPEC-GAP:` for, and why are most of them about determinism?
- What was the argument for a change ledger over a graph database?

---

## Phase 5 — Changing it safely

**Time:** 30 minutes. **Read this before your first commit.**

### The conventions

[`CLAUDE.md`](CLAUDE.md) § "Conventions this repo uses (learned, not to be reinvented)" is
the pre-flight checklist. Every item on it was learned the expensive way. The ones that bite
hardest:

- `Store.q()` is the only path to the database. A **third** exception to that rule has to
  make the argument again.
- `config.py` holds only *global* defaults; per-KPI alerting behaviour belongs in a
  `KpiContract`. Blurring that line is what makes the contract decorative.
- `SEED = 20260815` throughout, and several tests assert exact values downstream of it.
- A KPI's aggregation lives in its contract, not in the engine — and `agg="ratio"` must be
  wired in **all three** of `Store.series`, `Store.cohort_rows` and `contracts.freshness`.

### The tests that enforce them

| Test | What it protects |
|---|---|
| [`tests/test_docs.py`](tests/test_docs.py) | the README's own claims — the test count, every `config.PROVIDERS` row, the default model and its env var. **It fires on every change that adds a test**, so update the README's count in the *same* commit. |
| [`tests/test_pipeline.py`](tests/test_pipeline.py) | the acceptance test: it walks a finished card, collects every `query_id`, and asserts each still reproduces its logged output |
| [`tests/test_sparse_kpi.py`](tests/test_sparse_kpi.py) | generator fingerprints. **If one fails, fix the generator — never update the hash.** |
| [`tests/test_investigator.py`](tests/test_investigator.py) | `test_the_lane_cannot_change_a_single_score` — scores byte-identical with the LLM lane on and off |
| [`tests/test_entitlement.py`](tests/test_entitlement.py) | ranked order is stable across roles even though scores move |
| [`tests/test_anomaly.py`](tests/test_anomaly.py) | `test_mad_must_come_from_the_pre_window` — the anomaly must not define its own normal |
| [`tests/test_learning.py`](tests/test_learning.py) | a saturated prior still cannot lift a candidate over the floor |

Full suite (add the `env -u` prefix on a ROS machine):

```bash
.venv/bin/python -m pytest -q
```

### Recipes that already exist

Do not invent an approach — three decision records end with a worked procedure:

- **Add a KPI** → [`docs/contracts_decisions.md`](docs/contracts_decisions.md) §12, and
  [`docs/sparse_kpi_decisions.md`](docs/sparse_kpi_decisions.md) §12 if it is a ratio.
- **Add a persona** → [`docs/persona_decisions.md`](docs/persona_decisions.md) §12.
- **Add an LLM provider** → [`docs/ai_decisions.md`](docs/ai_decisions.md) §3 — one row in
  `config.PROVIDERS` and one adapter in [`ledgerlens/llm.py`](ledgerlens/llm.py). The
  `Provider` protocol has exactly one method and a test keeps it that way.

Each record also ends with a "what is deliberately not here" or "things not to do to this
code" section. Read the one for the subsystem you are touching first.

### You can now answer

- Why does the README's test count fail CI if you update it at the end of a branch instead
  of in each commit?
- Why must a new generated series take its own `np.random.default_rng(SEED_*)`?
- What is the correct response to a failing fingerprint test?

---

## Phase 6 — The submission

**Time:** 20 minutes.

- **[`docs/business_proposal.md`](docs/business_proposal.md)** — problem framing, solution
  design, target users, business case, roadmap, risks. Three appendices carry the
  scorecards: **Appendix A** maps each of the ten Minimum Prototype Expectations to the file
  that closes it, **Appendix B** does the same for the eight Round 2 objectives, and
  **Appendix C** states what is deliberately not built.
- **[`docs/demo_script.md`](docs/demo_script.md)** — the shot-by-shot script for the
  prototype video, including a "if something goes wrong on camera" section.
- **[`submission/README.md`](submission/README.md)** — how the PDFs and the deck are
  rebuilt from source. **The markdown is the authority**; the rendered artefacts in
  [`submission/`](submission) are outputs. Never hand-edit a PDF or the deck — edit the
  source and re-run [`docs/taskflow/build_deck.py`](docs/taskflow/build_deck.py).

---

## The whole repo, in one table

For a returning reader who knows what they want.

### Root

| Path | What it is |
|---|---|
| [`README.md`](README.md) | canonical description, and the honest scope of every claim |
| [`study_guide.md`](study_guide.md) | this file — the ordered path |
| [`CLAUDE.md`](CLAUDE.md) | project state, per-task summaries, and the conventions |
| [`config.py`](config.py) | global defaults, weights, thresholds, `SEED`, `PROVIDERS` |
| [`app.py`](app.py) | the Streamlit analyst UI |
| [`requirements.txt`](requirements.txt) · [`pyproject.toml`](pyproject.toml) | dependencies |

### Engine

| Path | What it is |
|---|---|
| [`ledgerlens/models.py`](ledgerlens/models.py) | Pydantic contracts and the cohort algebra |
| [`ledgerlens/contracts.py`](ledgerlens/contracts.py) | KPI semantic contracts: thresholds, lineage, access |
| [`ledgerlens/store.py`](ledgerlens/store.py) | DuckDB lifecycle and the query registry |
| [`ledgerlens/gen_data.py`](ledgerlens/gen_data.py) | seeded synthetic generator; writes the ground truth |
| [`ledgerlens/anomaly.py`](ledgerlens/anomaly.py) | detection, measurement, drill-down, BH |
| [`ledgerlens/ledger/connectors.py`](ledgerlens/ledger/connectors.py) | deterministic event ingestion → blast radius |
| [`ledgerlens/ledger/symptoms.py`](ledgerlens/ledger/symptoms.py) | ticket clustering |
| [`ledgerlens/hypothesis.py`](ledgerlens/hypothesis.py) | candidate generation and five-component scoring |
| [`ledgerlens/controls.py`](ledgerlens/controls.py) | negative control generation and evaluation |
| [`ledgerlens/learning.py`](ledgerlens/learning.py) | Beta–Bernoulli priors from analyst verdicts |
| [`ledgerlens/personas.py`](ledgerlens/personas.py) | persona and lever registries |
| [`ledgerlens/narrate.py`](ledgerlens/narrate.py) | template narrator + guarded LLM narration |
| [`ledgerlens/llm.py`](ledgerlens/llm.py) | the provider seam — gemini and anthropic adapters |
| [`ledgerlens/investigator.py`](ledgerlens/investigator.py) | the LLM lane: proposed checks, unverified causes, guard |
| [`ledgerlens/pipeline.py`](ledgerlens/pipeline.py) | orchestration: `diagnose()` and `run()` |

### Docs

| Path | What it is |
|---|---|
| [`docs/README.md`](docs/README.md) | the topical index — this guide's counterpart |
| [`docs/how_it_works.md`](docs/how_it_works.md) | the system from zero; start here |
| [`docs/contracts_decisions.md`](docs/contracts_decisions.md) | the KPI semantic contract |
| [`docs/persona_decisions.md`](docs/persona_decisions.md) | four personas, one computation |
| [`docs/sparse_kpi_decisions.md`](docs/sparse_kpi_decisions.md) | the sparse-history ratio KPI |
| [`docs/roles_decisions.md`](docs/roles_decisions.md) | role-based entitlement |
| [`docs/telemetry_decisions.md`](docs/telemetry_decisions.md) | latency, query accounting, cost |
| [`docs/abstention_decisions.md`](docs/abstention_decisions.md) | reachable refusal |
| [`docs/ai_decisions.md`](docs/ai_decisions.md) | the investigator lane, end to end |
| [`docs/learning_decisions.md`](docs/learning_decisions.md) | the feedback loop |
| [`docs/postwork_decisions.md`](docs/postwork_decisions.md) | the submission-hardening pass: proposal framing, demo figures |
| [`docs/business_proposal.md`](docs/business_proposal.md) | the Round 2 proposal + three scorecard appendices |
| [`docs/demo_script.md`](docs/demo_script.md) | the video shot script |
| [`docs/design/IMPLEMENTATION_SPEC.md`](docs/design/IMPLEMENTATION_SPEC.md) | the original build contract |
| [`docs/design/businessintelligence-ai-redesign.md`](docs/design/businessintelligence-ai-redesign.md) | the architecture rationale |
| [`docs/taskflow/`](docs/taskflow) | the implementation plans, kept as history |
| [`docs/screenshots/`](docs/screenshots) | the demo beats, captured |
| [`submission/`](submission) | rendered PDFs and deck — outputs, not sources |

`data/` is not listed because it does not exist at checkout: it is gitignored generator
output, rebuilt by `python -m ledgerlens.gen_data`.

---

## Ten questions to check yourself

If you can answer these, you understand this project end to end.

| # | Question | Answered in |
|---|---|---|
| 1 | What does an **omitted dimension** in a blast radius mean, and why does the campaign lose because of it? | [`how_it_works.md`](docs/how_it_works.md) §2, §6 |
| 2 | Why are there two baselines, and what breaks if you measure with the trailing one? | [`README.md`](README.md) § Design notes |
| 3 | What actually kills the decoy — the score, or the control? | [`how_it_works.md`](docs/how_it_works.md) §7 |
| 4 | Which two numbers on the page carry no `query_id`, and why is that defensible? | [`telemetry_decisions.md`](docs/telemetry_decisions.md) |
| 5 | Why does persona never change a number while role does? | [`persona_decisions.md`](docs/persona_decisions.md) §3, [`roles_decisions.md`](docs/roles_decisions.md) §4 |
| 6 | Name the three mechanisms preventing the LLM from changing a rank. | [`ai_decisions.md`](docs/ai_decisions.md) §3 |
| 7 | Why is the event normalizer *cut* rather than simply unbuilt? | [`ai_decisions.md`](docs/ai_decisions.md) §3 D2 |
| 8 | Why does the abstention path remove candidates rather than penalise them? | [`abstention_decisions.md`](docs/abstention_decisions.md) §3 |
| 9 | Why can a saturated learned prior never rescue a rejected hypothesis? | [`learning_decisions.md`](docs/learning_decisions.md) §2 |
| 10 | A fingerprint test fails after you touch the generator. What do you do? | [`CLAUDE.md`](CLAUDE.md) § Conventions |
