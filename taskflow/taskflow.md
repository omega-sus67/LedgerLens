# LedgerLens — Task Flow

Everything still standing between here and the **Aug 30** submission. Rewritten
**Aug 29** after tasks 1–3 landed, and **cut down to essentials only** — the original
twelve-task list is no longer achievable in the time left, so this file now carries the
four tasks that close real rubric rows plus one conditional, and states plainly what was
dropped and why.

Purpose: something the team can read, argue with, and split up. Each task below is
self-contained — goal, the rubric row it closes, files touched, subtasks, how it is
tested, and what could go wrong.

---

## 0. Where the repo actually is

**Verified Aug 29.** `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q`
→ **182 passed**.

Landed since this file was first written:

| Task | Closed | Record |
|---|---|---|
| **1 — KPI semantic contract** ✅ | contract, grains/cadences, freshness, lineage | [`docs/contracts_decisions.md`](../docs/contracts_decisions.md) |
| **2 — Personas + `Action` reshape** ✅ | persona narratives, levers/decision rights, confidence | [`docs/persona_decisions.md`](../docs/persona_decisions.md) · [`task_persona.md`](task_persona.md) |
| **3 — Third KPI, sparse history** ✅ | 3 KPIs / 3 sources, sparse-history scenario, ratio aggregation | [`docs/sparse_kpi_decisions.md`](../docs/sparse_kpi_decisions.md) · [`task_sparse_kpi.md`](task_sparse_kpi.md) |

### The three things that would have bitten us — **all closed by Task 0 ✅**

1. ~~**Nothing is pushed. The remote is still at Aug 16.**~~ **Done.** `task-2-personas`
   and `task-3-sparse-kpi` were fast-forwarded into `main` and pushed; `origin/main` is
   at `3364b62`. Verified by cold-cloning the public repo into `/tmp` and following only
   the README: 184 tests pass and `python -m ledgerlens.pipeline` reproduces the full
   diagnosis card, decoy rejection included, with `ANTHROPIC_API_KEY` unset.

2. ~~**The README's test count is a claim, and it is now false.**~~ **Done.** `126` →
   `184` in both places, and `CLAUDE.md` updated. The count is **184, not 182**, because
   `tests/test_docs.py` adds two tests that count themselves. That file now asserts the
   README's number against `pytest --collect-only`, so drift is a test failure rather
   than a credibility leak.

3. ~~**`config.py:123` is not a valid model id.**~~ **Done, but the premise was wrong.**
   `claude-sonnet-4-6` *is* a real model id — Claude Sonnet 4.6, still served, at
   $3/$15 per MTok. It was **stale, not invalid**, so the "a judge who knows the API
   will notice" argument does not hold. Changed to `claude-sonnet-5` anyway: it is the
   current Sonnet (cheaper at $2/$10, more capable) and it is the string Task 6's
   telemetry copy quotes, so the two now agree. `tests/test_docs.py` pins it.

### Running the tests on this machine

The ROS 2 install poisons `PYTHONPATH`. Without stripping it, pytest dies at collection
with `ModuleNotFoundError: No module named 'yaml'`:

```bash
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q
```

---

## What the rubric actually asks

The brief has **two** lists and they are not equally weighted. *Minimum Prototype
Expectations* is the concrete checklist a judge ticks — a missing row is a zero, not a
deduction. *Round 2 Objectives* and *Real-World Complexities* reward depth, but no
single one of them is fatal. The cut below follows that distinction.

| # | Minimum Prototype Expectation | Status |
|---|---|---|
| 1 | Three to five connected KPIs across two or three data sources with different grains or refresh cadences | ✅ Task 3 |
| 2 | A lightweight KPI or semantic contract covering definitions, calculations, drivers, thresholds, lineage and access restrictions | ✅ Task 1 |
| 3 | At least two personas receiving different insight narratives or recommended actions | ✅ Task 2 — four |
| 4 | One multi-factor KPI movement with known or simulated underlying drivers | ✅ seasonality + deploy + campaign decoy, decomposed on the card |
| 5 | One low-confidence scenario in which the engine requests clarification or abstains | ✅ Task 3 declines detection and asks for a window · ✅ Task 7 makes the refuse-to-explain branch reachable from the sidebar |
| 6 | One sparse-history or newly launched KPI scenario | ✅ Task 3 |
| 7 | One role-based security or entitlement scenario | ✅ Task 4 — `fin.rail_detail` redacts the rail cut from `growth`, and the card names the policy |
| 8 | Evidence showing source freshness, analytical method, contribution, confidence and lineage | ✅ Tasks 1 + 2 |
| 9 | A clear breakdown of LLM versus non-LLM processing | ✅ Task 6 — the ⏱ panel, on the page |
| 10 | Runtime telemetry covering latency, model calls, token usage and estimated cost | ✅ Task 6 |

**TEN OF TEN CLOSE.** Task 7 hardens row 5; task 12 is the submission package.

---

## Task order

| # | Task | Closes | Est. |
|---|---|---|---|
| ~~0~~ | ~~Merge, correct the claims, push~~ ✅ | the *repository* deliverable | done |
| ~~4~~ | ~~Role-based entitlement~~ ✅ | MPE row 7 | done |
| ~~6~~ | ~~Telemetry panel~~ ✅ | MPE rows 9 **and** 10 | done |
| ~~7~~ | ~~Abstention demo path~~ ✅ | hardens MPE row 5 | done |
| 12 | Submission package | proposal · video · README · repo | 4h |
| 5 | Learning-loop UI *(conditional)* | Objective 7 — **only if 12 is done** | 2h |

**Cut line if behind:** drop 5, then the P2 items inside 12 (charts, watchtower
landing). **Never drop 0 or 12** — those are deliverables, not features, and a missing
deliverable is a different order of failure from a missing feature.

---

## Task 0 — Merge, correct the claims, push

**Goal:** make the public repo contain the work. Everything else is worthless if this
does not happen, and it is the only task with no technical risk.

**Files:** `README.md`, `CLAUDE.md`, `config.py`, git

### 0.1 — Land the stack

Both feature branches are green and stacked. Merge in order, fast-forward:

```bash
git checkout main
git merge --ff-only task-2-personas
git merge --ff-only task-3-sparse-kpi
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q   # must be 182
```

### 0.2 — Make the claims true again

- `README.md:46` and `README.md:268` — `126 tests` → the real number.
- `CLAUDE.md:20` — same, plus update the "current state" block: tasks 1–3 are done.
- `config.py:123` — `MODEL = "claude-sonnet-4-6"` → `"claude-sonnet-5"`.

Add a test so the count cannot rot again:

```python
# tests/test_docs.py
from pathlib import Path

import config


def test_readme_test_count_is_true():
    """The README's numbers are the product's credibility. A count that drifts is the
    one error that costs more than the thing it misstates."""
    import re
    import subprocess

    out = subprocess.run(
        ["env", "-u", "PYTHONPATH", "-u", "AMENT_PREFIX_PATH",
         ".venv/bin/python", "-m", "pytest", "--collect-only", "-q"],
        capture_output=True, text=True, cwd=config.ROOT,
    ).stdout
    actual = int(re.search(r"(\d+) tests? collected", out).group(1))
    claimed = {int(m) for m in re.findall(r"(\d+) tests", Path("README.md").read_text())}
    assert claimed == {actual}, f"README claims {claimed}, suite has {actual}"
```

> Guard against recursion: this test shells out to `--collect-only`, which does not run
> the suite. Do **not** call `pytest` proper from inside a test.

### 0.3 — Push

```bash
git push -u origin main
gh repo view --json visibility   # must be PUBLIC
```

**Test:** `git log origin/main -1` is today's commit; a fresh `git clone` into `/tmp`
plus the README's documented install steps reproduces the diagnosis card.

**Risk:** none technical. The risk is that it keeps getting deferred behind feature
work. It is Task 0 for that reason.

---

## Task 4 — Role-based entitlement ✅ **DONE**

> **Landed 2026-08-30** on `task-4-entitlement`. Decisions:
> [`docs/roles_decisions.md`](../docs/roles_decisions.md). Plan as executed:
> [`roles_tasks.md`](roles_tasks.md). Three errors in the sketch below were corrected
> during implementation — the scores are *not* identical across roles, the engine must
> use the *lenient* contract lookup, and `run()` had no `persona` parameter. The
> corrected reasoning is in the decisions doc; the sketch is kept for history.

**Goal:** redaction *with provenance* — the auditability story the rest of the system
already tells. Closes MPE row 7, the only uncovered row.

**Files:** `ledgerlens/pipeline.py`, `app.py`, `tests/test_entitlement.py`

The machinery all exists, and Task 2 wired the last missing piece:

- `contracts.visible_drill_dims(role)` returns `DRILL_DIMS` minus policy-hidden dims
- `anomaly.drill(store, root, dims)` already takes a `dims` list
- `AccessRule(policy_id="fin.rail_detail", role="growth", hidden_dims=["payment_rail"])`
  is already declared on the `mrr_renewals` contract
- **`Persona.role` is live** and `test_growth_role_matches_the_contract_access_rule`
  already joins the persona registry to the contract's roles

### 4.1 — Thread the role into drill

[`pipeline.py:60`](../ledgerlens/pipeline.py#L60) currently passes the global list:

```python
nodes = anomaly.drill(store, root, config.DRILL_DIMS)
```

`diagnose()` gains `role: str | None = None`, and:

```python
    dims = (
        contracts.get(metric).visible_drill_dims(role)
        if role is not None
        else config.DRILL_DIMS
    )
    nodes = anomaly.drill(store, root, dims)
```

### 4.2 — Redact visibly, never silently

The point is the **honest refusal**. Return what was withheld and why, so the card can
say it. Add to `NarrationPayload`:

```python
    redactions: list[tuple[str, str, str]] = field(default_factory=list)  # (dim, policy_id, reason)
```

`NarrationPayload` is a `@dataclass`, not a pydantic model, so this needs
`from dataclasses import dataclass, field` at the top of `narrate.py`, and the field
must come after the existing defaulted `no_confident_cause`.

populated in `diagnose()` from `contracts.get(metric).access` for the caller's role.
`_cause_card` renders one line per redaction:

> 2 deeper slices redacted by policy `fin.rail_detail` — payment-rail revenue splits
> are finance-restricted; growth sees region and segment cuts only.

Policy id and reason come from the `AccessRule`, never hardcoded.

### 4.3 — Wire it to the persona selector

`app.py` already has `who = personas.get(persona_id)`. Pass `who.role` into
`load_payload`, **and add it to the cache key** — entitlement changes which dims are
drilled, so it changes the payload. This is the half of the cache-key debt
[`docs/persona_decisions.md`](../docs/persona_decisions.md) §10 explicitly left unpaid,
and the docstring on `load_payload` says so.

**Test** (`tests/test_entitlement.py`):

```python
def test_growth_never_sees_a_payment_rail_cut(store):
    payload = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="growth")
    assert all("payment_rail" not in n.cohort for n in payload.nodes)


def test_analyst_still_sees_every_cut(store):
    payload = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="analyst")
    assert any("payment_rail" in n.cohort for n in payload.nodes)


def test_redaction_names_its_policy(store):
    card = pipeline.run("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store,
                        persona=personas.get("growth"))
    assert "fin.rail_detail" in card.summary or any(
        "fin.rail_detail" in s.claim for s in card.causal_chain
    )


def test_redaction_does_not_change_the_ranking_inputs(store):
    """Entitlement hides CUTS, not rows. The candidate set and their scores must be
    identical -- a policy that silently changed the answer would be a security hole
    dressed as a feature."""
    a = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="analyst")
    g = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="growth")
    assert [h.event.event_id for h in a.ranked] == [h.event.event_id for h in g.ranked]
```

**Risk:** the focal cohort is currently `DACH · Enterprise · sepa`. Hiding
`payment_rail` from `growth` changes which cohort becomes focal, which changes the
headline number on that persona's card. That is **correct** — they are entitled to a
shallower answer — but it will look like a bug on stage if nobody says so. The
redaction line is what makes it read as policy rather than breakage. Do not skip it.

---

## Task 6 — Telemetry panel ✅ **DONE**

> **Landed 2026-08-30** on `task-6-telemetry`. Decisions:
> [`docs/telemetry_decisions.md`](../docs/telemetry_decisions.md). Plan as executed:
> [`telemetry_tasks.md`](telemetry_tasks.md). Three errors in the sketch below were
> corrected during implementation — `queries` is three different numbers and the draft
> picked the one that understates the work ~6x; the five-stage assertion breaks on the
> manual-window path; and timings are cache-dependent enough that no duration may be
> asserted. Corrected reasoning in the decisions doc; the sketch is kept for history.

**Goal:** the runtime-constraints row, and it doubles as the LLM-vs-non-LLM breakdown
**in the UI**, where judges look — today that claim lives only in the README. Closes
two MPE rows for one task's work.

**Files:** `ledgerlens/pipeline.py`, `ledgerlens/models.py`, `app.py`

### 6.1 — Time the stages

`diagnose()` already runs five distinct phases: detect, drill, symptoms, rank,
seasonal. Wrap each in `time.perf_counter()` and collect into a dict. Add to
`NarrationPayload` and carry through to `DiagnosisCard`:

```python
class Telemetry(BaseModel):
    model_config = ConfigDict(frozen=True)
    stage_ms: dict[str, float]
    total_ms: float
    queries: int         # len(pipeline.card_query_ids(card))
    llm_calls: int = 0
    llm_tokens: int = 0
    llm_cost_usd: float = 0.0
```

`DiagnosisCard` gains `telemetry: Telemetry | None = None` (pydantic, frozen, so a
default keeps every existing construction site valid), and `_cause_card` /
`_no_cause_card` pass `payload.telemetry` straight through — narration must not
recompute it, for the same reason it recomputes no other number.

`tests/test_pipeline.py:130` already uses `perf_counter` for a latency assertion —
same pattern, do not invent a second one.

> `queries` cannot be filled inside `diagnose()`: `card_query_ids()` needs the finished
> card. Count it in `narrate()` where the card is assembled, or leave it `0` in the
> payload and set it via `model_copy` at the end of `_cause_card`.

### 6.2 — Render it, and make the zero the point

```python
with st.expander("⏱ Telemetry — latency, model calls, cost"):
```

Show the stage breakdown as a table, then the sentence that turns the zero into a
claim rather than an absence:

> **This diagnosis: 0 LLM calls, 0 tokens, $0.0000.** Every number on this page came
> from a logged SQL query with a replayable `query_id`. The ranking path is
> deterministic Python and SQL by design, not by omission — which is why the full test
> suite and the entire demo run with `ANTHROPIC_API_KEY` unset.

Then the honest counterfactual, so it does not read as dodging the question:

> With the optional LLM narrator enabled, narration alone would add ~1 call and
> ~2k tokens per diagnosis on `claude-sonnet-5`. It would change the prose and none
> of the numbers.

**Test:**

```python
def test_telemetry_reports_every_stage(store):
    card = pipeline.run("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    t = card.telemetry
    assert set(t.stage_ms) == {"detect", "drill", "symptoms", "rank", "seasonal"}
    assert t.total_ms >= sum(t.stage_ms.values()) * 0.9
    assert t.queries == len(pipeline.card_query_ids(card))


def test_offline_path_makes_no_model_calls(store):
    """The claim the README rests on, asserted rather than stated."""
    card = pipeline.run("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    assert (card.telemetry.llm_calls, card.telemetry.llm_cost_usd) == (0, 0.0)
```

**Risk:** timings vary run to run, so assert **structure and zero**, never a duration.
`test_pipeline.py`'s existing latency test already has a generous bound — do not tighten
it to make telemetry look good.

---

## Task 7 — Abstention demo path ✅ **DONE**

> **Landed 2026-08-30** on `task-7-abstention`. Decisions:
> [`docs/abstention_decisions.md`](../docs/abstention_decisions.md). The sketch below is
> right about the mechanism and the risk (the decoy does stay rejected, at 0.322), but
> missed one thing: `_no_cause_card` hardcoded its connectivity prose, so the simulation
> made the card claim github was connected while the demo said it was not. Connectivity
> is now read off the contract's lineage.

**Goal:** abstention **demonstrated**, not described. The code path exists and is
already written well; there is simply no way to reach it without editing source.
Cheapest item on the list.

**Files:** `app.py`, `ledgerlens/pipeline.py`, `ledgerlens/hypothesis.py`

### 7.1 — A source-drop switch

`hypothesis.candidates(store, a)` iterates `store.events()`. Add an optional filter
threaded from `diagnose()`:

```python
def candidates(store: Store, a: Anomaly, drop_sources: frozenset[str] = frozenset()):
    ...
        if ev.source in drop_sources:
            continue
```

`diagnose(..., drop_sources=frozenset())` passes it to `hypothesis.rank`.

### 7.2 — Sidebar toggle

> ☐ Simulate: deploy source (github) not connected

On: `drop_sources={"github"}` → the SEPA deploy never becomes a candidate → nothing
clears `config.SCORE_FLOOR` → `_no_cause_card()` renders. It **already** emits exactly
the right thing: which sources are and are not connected, plus a P1 action to *"connect
{missing} so the next incident of this shape has candidates to test"*.

**Must join the `load_payload` cache key** — same reason as role and window.

**Test:**

```python
def test_dropping_the_deploy_source_forces_abstention(store):
    payload = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store,
                                drop_sources=frozenset({"github"}))
    assert payload.no_confident_cause is True
    card = narrate.narrate(payload)
    assert card.no_confident_cause is True
    assert "not connected" in card.summary.lower()
    assert card.actions[0].lever == "connect_source"


def test_abstention_is_identical_for_every_persona(store):
    """Already asserted in test_narrate_personas.py, re-asserted on the REACHABLE
    path: a CFO must not be handed a confident answer the analyst was refused."""
    payload = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store,
                                drop_sources=frozenset({"github"}))
    for pid in ("analyst", "cfo", "oncall", "growth"):
        assert narrate.narrate(payload, persona=personas.get(pid)).no_confident_cause
```

**Risk:** dropping `github` also removes the *other* eight deploys, so verify the
campaign decoy does not accidentally win. It should not — its `N` is 0.0 from the
segment-sibling control, so it is rejected outright rather than promoted. Assert that
explicitly if the first run surprises you.

---

## Task 12 — Submission package

**Goal:** the three things the brief literally asks you to hand in. **Not optional, and
not a checklist row** — a missing deliverable is a different order of failure from a
missing feature.

> **What Round 2 Asks You to Deliver:** Detailed Business Proposal · Working Prototype ·
> Public GitHub repository, including a prototype demo video and a README

**Files:** `README.md`, `docs/business_proposal.md`, `requirements.txt`, `mockups/`

### 12.1 — Requirement map in the README (do this first)

A table with a row per rubric line → where it lives in the repo, with file links. Makes
grading effortless and costs an hour. The three decisions docs are already written; this
is the index over them.

### 12.2 — `requirements.txt`

```bash
uv pip compile --python .venv/bin/python -o requirements.txt - <<'EOF'
duckdb
pandas
pyarrow
numpy
scipy
statsmodels
pydantic
streamlit<1.63
plotly
anthropic
pytest
EOF
```

So the install claim survives a judge's laptop. Verify by cold-cloning into `/tmp` and
following only the README.

### 12.3 — Business proposal (`docs/business_proposal.md`)

Mostly assembly — the material exists:

| Section | Source |
|---|---|
| Problem framing | `README.md` opening + `businessintelligence-ai-redesign.md` |
| Solution design | the three `docs/*_decisions.md` |
| Target users | the four personas, with channels and decision rights |
| Business case | the −$410k incident: days of analyst time vs a sub-second diagnosis |
| Phased roadmap | §10 of the redesign doc, plus the cut list at the foot of this file — the honest "what's next" |
| Risks + mitigations | the README's "what this does and does not claim" section is already this |

### 12.4 — Screenshots

`../mockups/` has six rendered screens (`mock_1_dashboard_alert.png` …
`mock_6_release_watch.png`). Mirror the live UI against them and embed 3–4 in the README.

### 12.5 — Demo video

Beats, in order:

1. **The pain** — dashboards say *what*, not *why*; days of analyst time.
2. **The anomaly** — `mrr_renewals` down 8.3%, and the card separates 1.2% seasonality
   from the 7.0% that is real.
3. **The drill-down** — narrowed to `DACH · Enterprise · sepa`, 3 of 99 slices.
4. **Linger on the decoy.** The marketing cut is temporally *more* plausible and dies
   anyway, by a control that predicted DACH Mid/SMB should also drop — they came in
   flat at −1.3%. Show the control table. **This is the single most persuasive 20
   seconds in the product.**
5. **Same evidence, four audiences** — flip the persona selector. CFO gets dollars and
   an escalation; on-call gets the sha and a rollback. Say the query ids are identical.
6. **The rate KPI that refuses** — insufficient history, declines to detect, asks for a
   window, then explains it anyway.
7. **Entitlement** (Task 4) — growth loses the rail cut, and the card names the policy.
8. **Close on telemetry** (Task 6) — *"and when it doesn't know, it says so — for
   $0.0000 per diagnosis, with every number traceable to a logged query."*

**P2, only if the video is already recorded:** two `plotly` charts (`plotly` is already
a dependency and `app.py` has zero plots) — the focal series with the frozen Theil–Sen
baseline overlaid and the anomaly window shaded, and an attribution treemap. The first
is the most persuasive single image this system can produce. And the watchtower landing
page, which reframes the product from "tool you point" to "engine that surfaces".

**Risk:** this task is four hours of assembly with no technical difficulty, which makes
it the easiest to underestimate and the most expensive to run out of time on. Start it
before the last feature, not after.

---

## Task 5 — Learning-loop UI *(conditional: only if Task 12 is finished)*

**Goal:** Round 2 **Objective 7** — *"Mechanism to learn from analyst and business-user
feedback."* An objective, not an MPE row, which is why it sits below the cut line.

**Files:** `app.py`, `tests/`

`learning.record()` and `learning.prior()` both exist and are wired to the `verdict`
table; nothing calls `record`. `prior()` counts rows at read time, so the **P**
component moves with no other plumbing: Beta(1,1) = 0.50 → one confirm → Beta(2,1) =
**0.67**.

- Confirm / Reject / Correct buttons on each hypothesis in `render_hypothesis()`
- on click: `learning.record(store, ...)` → `st.cache_resource.clear()` → `st.rerun()`
- show before/after next to the P bar — a 15-second video beat

**Risk — decide this before recording.** `verdict` rows persist in
`data/ledgerlens.duckdb`. Repeated demo clicks drift the priors away from the numbers in
the README and in `tests/test_app.py` (`scores[0] == "0.700"`). Ship a **"reset
feedback"** button in the sidebar, or delete the db before recording. A demo that
contradicts the README is worse than no demo of this feature.

---

## Cut, and why

Dropped deliberately, not forgotten. Each one is named in the business proposal's
roadmap as next-phase work — a gap we can point at beats a gap a judge finds.

| Task | Est. | Why it is safe to drop |
|---|---|---|
| **8 — LLM narrator** | 3h | Row 9 asks us to *explain* the LLM/non-LLM split, not to make calls. **"0 LLM calls, $0.0000 per diagnosis, every number from a logged query"** is a stronger answer than one API call, and Task 6 puts it on screen. The one-line model-id fix is kept in Task 0. |
| **9 — effect CI** | 3h | Materiality-as-statistics is a *Complexity*, not an MPE row. The README already states plainly that the −$410k figure has no interval behind it. A documented honest gap reads better than a rushed bootstrap nobody had time to validate. |
| **10 — Slack ingest** | 2h | "Heterogeneous sources" is already covered by three KPIs across three systems plus four ledger connectors. Genuinely redundant. `data/slack.json` stays generated and unread — note it in the roadmap. |
| **11 — ambiguity** | 3h | Highest risk on the board: needs a `gen_data.py` change to manufacture a near-tie, and would break `test_hypothesis.py:89`, which asserts the top-two gap *exceeds* `AMBIGUITY_EPSILON`. Maps to no MPE row. `DiagnosisCard.open_question` stays `None`. |

**~11 hours freed.** Kept work is ~8h plus the conditional.

---

## Cross-cutting notes

**The `load_payload` cache key.** **PAID in task 4** -- the key is now
`(metric, as_of_iso, cohort_key, window_key, role_key)` and task 7's `drop_sources`
slots into the same signature. Historical note follows. Half-paid. Task 2 moved the boundary *below*
narration, so persona needs no key. Tasks 4 (role), 5 (feedback) and 7 (dropped
sources) all change the **payload** and therefore all **must** join the key — Task 3
already added cohort and window. Fix the signature once, in Task 4, rather than three
times. The docstring on `load_payload` carries this warning.

**`gen_data.py` is the fragile one.** Nothing in this cut list touches it — that is one
of the reasons Task 11 was dropped. If something changes anyway: it uses one sequential
RNG stream, so any new series needs its own `default_rng(SEED_*)`, and
`tests/test_sparse_kpi.py`'s fingerprints must stay green. **If a fingerprint fails, fix
the generator, never the hash.**

**Test count is a claim.** 229 today. `tests/test_docs.py` fires on EVERY task that
adds tests, so update `README.md`'s number in the same commit -- otherwise every
intermediate commit on a branch is red. Tasks 4, 6 and 7 all add tests. Task 0's
`test_readme_test_count_is_true` makes drift a test failure instead of a credibility
leak — keep it passing rather than deleting it when it goes red.

**Every number still needs a `query_id`.** `Store.q` remains the only path to the
database. Telemetry (Task 6) is the one legitimate exception: latency is a fact about
the process, not about the data, and it carries no `query_id` because there is no query
behind it. Say so in the panel rather than leaving a judge to wonder.
