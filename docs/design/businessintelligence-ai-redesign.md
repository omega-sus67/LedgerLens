# BusinessIntelligence.ai — Redesigned: The Change Ledger Architecture

**Working name:** LedgerLens (rename freely)
**One-line pitch:** Root-cause analysis as a *set intersection over a ledger of business changes*, verified by negative controls — not a knowledge-graph guessing game.
**Target:** Accenture Innovation Challenge 2026, Round 1 (3 slides + 3-min video), buildable prototype in ~1 day for the demo video.

---

## 0. Deadline scope — read this first (submission 23:59 tonight, Aug 16)

Round 1 asks for a **deck and a 3-minute video, nothing else**. The brief says explicitly: *"You don't need a fully developed solution yet"* — concept stage, creativity over technical precision. **No code is required tonight.**

Order of work tonight:
1. **Deck** (~2h): fill the official template — slides 4/5/6 content is already drafted; team slide; delete the instructions slide; `TeamName_IdeaName.pptx` naming; Arial; spell check.
2. **Video** (~2–3h): script + record a 3-minute *explainer* — the two diagrams, the decoy-rejection walkthrough as a storyboard. A static mock of the hypothesis card is fine **presented as a design mock**; do not imply a working product exists.
3. Submit. Then sleep.

Build the prototype against `IMPLEMENTATION_SPEC.md` *after* submission, for Round 2. Only if the deck and video are done with ≥4 hours to spare should you attempt the MVP-for-video path (spec §12) to get real screenshots — anything tighter risks the submission for a nice-to-have.

---

## 1. TL;DR — What changed and why

The Gemini architecture was a stack of five heavyweight frameworks (cognee, Neo4j, DoWhy, LangGraph, Qdrant) wired around a claim ("0% hallucinated causality") that the design cannot actually deliver. The redesign keeps the same four-phase *story* — what changed → what could explain it → which explanation survives → what to do — but rebuilds it on one cheap, deterministic primitive and pushes the LLM to the edges of the system.

| Concern | Gemini plan | Redesign | Why |
|---|---|---|---|
| Context linkage | cognee GraphRAG + Neo4j: LLM extracts entities/relations from text | **Change Ledger**: one table of typed events, each with a machine-readable *blast radius* | 90% of enterprise linkage is already deterministic (deploy → service → region; ticket → account → segment). Foreign keys beat LLM entity extraction on cost, latency, and error rate. |
| Causality | DoWhy SCM "validation" | Cohort intersection + **negative controls** + diff-in-diff effect size | DoWhy estimates effects *given* a DAG you assert; with N=1 incidents there is no population to estimate over. Controls and counterfactual baselines are the correct formalism and are explainable to a judge. |
| Anomaly detection | STL at 2.5σ over the full dimension cross-product | STL/MAD residuals + **hierarchical drill-down** (test children only where the parent is anomalous) | The cross-product is thousands of simultaneous tests → false-alarm storm. Top-down attribution bounds the test count and gives contribution-to-delta for free. |
| Orchestration | LangGraph state machine | Plain Python functions in a pipeline | The flow is a straight DAG with one loop (ambiguity → widen search). A framework adds surface area, not capability, at hackathon scale. |
| Confidence | LLM-emitted "85% / 15%" | Scored rubric of **named, auditable components**, each backed by a SQL query | A number a judge can't audit is a number that costs you points. |
| Ambiguity | Unaddressed (fake percentages) | First-class output: the **discriminating test** that would separate the surviving hypotheses | Directly answers the brief's hardest "Think about" bullet. |
| LLM role | Everywhere (extraction, reasoning, scoring, narration) | **Investigator at the edges**: reads messy context, proposes checks from a template vocabulary, names causes outside the connected data, narrates the evidence — but never decides the verdict | An LLM that *decides* is a place the system can silently lie; an LLM that *proposes into deterministic verification* is leverage. |

**Honest framing (use these words in the deck):** pitch it as **"an AI business investigator that generates and tests root-cause hypotheses against enterprise evidence."** Not a "causal inference engine" (indefensible under questioning), and not "a deterministic engine with an LLM narrator" (undersells it at an AI challenge). Do **not** put "only two LLM calls" in any judge-facing material — the call-site discipline is an engineering constraint for the README, not a selling point.

---

## 2. Design principles

1. **Deterministic core, probabilistic edges.** Everything between raw data and the ranked hypothesis list is SQL and arithmetic. LLMs touch data only on the way in (schema normalization) and the way out (narration), and both calls are Pydantic-validated.
2. **Every claim carries its query.** Each evidence bullet in the final narrative links to the exact SQL that produced it. The analyst can click and re-run it. This is the anti-hallucination mechanism — not a bigger model.
3. **Ambiguity is an output, not a failure.** When two hypotheses survive, the system's job is to say what test separates them, not to invent a percentage.
4. **The demo shows a rejection, not just a detection.** The memorable 15 seconds of the video is the system throwing out a plausible decoy because its blast radius doesn't match the affected cohort.
5. **The LLM proposes; the evidence disposes.** Four call sites — context extraction, test proposal, unverifiable-cause listing, narration — all *additive* and template-gated. Nothing an LLM emits can reorder the deterministic ranking or override a control result, and everything it emits carries a visible provenance label.

---

## 3. Architecture

```
                        ┌─────────────────────────────────────────────┐
                        │            DATA (all synthetic for demo)     │
                        │  metrics.parquet   deploys.json  flags.json  │
                        │  campaigns.csv     zendesk.json  slack.json  │
                        └──────────┬──────────────────────┬───────────┘
                                   │ structured           │ unstructured
                                   ▼                      ▼
                    ┌──────────────────────┐   ┌─────────────────────────┐
                    │ 1. METRIC STORE      │   │ 2. CHANGE LEDGER        │
                    │    DuckDB star schema│   │    one events table     │
                    │    (fact + dims)     │   │  deterministic connectors│
                    └──────────┬───────────┘   │  + LLM normalizer (only │
                               │               │    for Slack/tickets,   │
                               ▼               │    Pydantic-validated)  │
                    ┌──────────────────────┐   └───────────┬─────────────┘
                    │ 3. ANOMALY ENGINE    │               │
                    │  STL residual / MAD  │               │
                    │  hierarchical drill- │               │
                    │  down + contribution │               │
                    └──────────┬───────────┘               │
                               │  anomaly = {metric, cohort │
                               │  predicate, window, delta} │
                               ▼                            ▼
                    ┌────────────────────────────────────────────────┐
                    │ 4. HYPOTHESIS ENGINE (pure SQL + arithmetic)   │
                    │   candidates = events WHERE                    │
                    │     time overlaps/precedes anomaly window      │
                    │     AND blast_radius ∩ anomaly cohort ≠ ∅      │
                    │   score = w·[Temporal, CohortMatch,            │
                    │             DoseResponse, ControlsPassed,      │
                    │             LearnedPrior]                      │
                    │   negative controls auto-generated per         │
                    │   candidate; diff-in-diff effect size          │
                    └──────────┬─────────────────────┬───────────────┘
                               │ clear winner        │ scores too close
                               ▼                     ▼
                    ┌──────────────────┐   ┌──────────────────────────┐
                    │ 5. NARRATIVE     │   │ 5b. DISCRIMINATING TEST  │
                    │  one LLM call,   │   │  find the predicate where │
                    │  strict schema,  │   │  H1 and H2 predict        │
                    │  every bullet →  │   │  different behavior; emit │
                    │  query id        │   │  the query/experiment     │
                    └──────────┬───────┘   └──────────┬───────────────┘
                               └──────────┬───────────┘
                                          ▼
                    ┌────────────────────────────────────────────────┐
                    │ 6. ANALYST UI (Streamlit)                      │
                    │  anomaly card → attribution treemap →          │
                    │  ranked hypotheses w/ evidence → confirm/reject │
                    │  → label stored → LEARNING LOOP (priors update)│
                    └────────────────────────────────────────────────┘
```

The pipeline is ~6 Python modules and one DuckDB file. No graph database, no vector database, no agent framework — each of those is a Round 2 extension (Section 10), not a Round 1 dependency.

---

## 4. Component deep-dives

### 4.1 Metric store — DuckDB

**What it is.** An in-process columnar OLAP engine: a single file, imported as a Python library, that runs vectorized SQL over Parquet/CSV at millions of rows per second.

**Why it's right here.** The anomaly and hypothesis stages are nothing but group-bys, window functions, and joins over a fact table. DuckDB gives warehouse-grade speed with zero infrastructure — critical when you have one day and the demo must run on a laptop, and honest to the enterprise story ("swap the file for Snowflake/BigQuery; the SQL is the same").

**Schema (star):**

```sql
fact_metric(date, metric_name, region, segment, payment_rail, product, value)
-- dims are low-cardinality columns kept inline; no separate dim tables needed at demo scale
```

### 4.2 Anomaly engine — decomposition + hierarchical drill-down

**The problem with the old plan.** Testing Region × Product × Tier × Channel at 2.5σ is thousands of simultaneous hypothesis tests. At 2.5σ you expect a false flag roughly every ~80 slices *per day* — the system cries wolf before it ever meets a real incident.

**The fix — test top-down, not everywhere:**

1. Test the aggregate metric first. Deseasonalize with STL (`statsmodels.tsa.seasonal.STL`) if you have 2+ clean seasonal cycles; otherwise fall back to a **rolling-median + MAD z-score**, which is robust to outliers and needs far less history. Flag when `|residual| > k·MAD` for 2+ consecutive periods.
2. Only if a node is anomalous, expand its children along one dimension at a time and compute each child's **contribution to the parent's delta**: `contrib(child) = Δchild / Δparent`.
3. Recurse into children that are both anomalous and materially contributing (e.g. >20% of parent delta). Apply Benjamini–Hochberg within each level if you want the extra rigor line for Q&A.

This bounds the number of tests to the anomalous path instead of the full cross-product, and its output is exactly what the business wants anyway: *"91% of the drop is DACH × Enterprise × SEPA renewals."* (This is the industrial-standard approach — Adtributor/Squeeze family of algorithms — which is a nice literature name-drop for judges.)

**Output object:**

```python
Anomaly(metric="mrr", cohort={"region": "DACH", "segment": "Enterprise", "payment_rail": "sepa"},
        window=("2026-08-03", "2026-08-10"), delta_pct=-8.2, contribution=0.91,
        expected=..., actual=..., residual_z=...)
```

### 4.3 The Change Ledger — the core primitive

**What it is.** One append-only table where *every deliberate or observable change in the business* becomes a typed event with a timestamp and a **blast radius**: a set of dimension predicates describing exactly which slices of the business the event could plausibly touch.

```python
class ChangeEvent(BaseModel):
    event_id: str
    event_type: Literal["deploy", "feature_flag", "price_change", "campaign",
                        "policy_change", "vendor_incident", "external"]
    ts_start: datetime
    ts_end: datetime | None          # None = still in effect
    source: str                      # "github", "launchdarkly", "pricing_db", "slack", "zendesk"
    blast_radius: dict[str, list[str]]   # {"region": ["DACH"], "payment_rail": ["sepa"]}
    description: str
    evidence_refs: list[str]         # ticket ids, PR urls, message permalinks
```

**Why this replaces cognee + Neo4j.** The insight is that in a real enterprise, the linkage the Gemini plan wants an LLM to *infer* is mostly *already recorded*: a deploy knows its service and rollout cohort, a feature flag knows its targeting rules, a campaign knows its geo, a Zendesk ticket knows its account and the account knows its segment. Blast radius = those facts, expressed as dimension predicates — which makes "is this event relevant to this anomaly?" a **SQL intersection**, not a graph traversal or an embedding similarity. Deterministic, sub-millisecond, and explainable in one sentence to a non-technical judge.

**Ingestion, two lanes:**

- *Deterministic connectors (most events):* parse deploy logs, flag configs, campaign calendars, pricing table diffs directly into `ChangeEvent`. No LLM involved. For the demo these read the synthetic JSON files.
- *LLM normalizer (unstructured only):* Slack messages and support tickets go through one structured-output LLM call whose *only* job is to fill the `ChangeEvent` schema (or emit a `TicketCluster` signal — see below). Pydantic validation rejects malformed output and re-asks. The LLM never decides *relevance*; it only normalizes *format*.

**Can the linkage be wrong? Yes — wrong, but not invented.** Three failure modes, honestly: (1) LLM-inferred radii on unstructured events — guarded by rejecting dimension values outside the known universe, multiplying the hypothesis score by the extraction `confidence`, and an "inferred — verify" badge in the UI; (2) wrong metadata at the source — garbage in, but it points at a specific row a human can open and fix; (3) the declared mapping itself missing a ripple effect. The saving property is the *direction* of failure: a too-wide radius fails its negative controls, a too-narrow one leaves nothing above the score floor and the system says "cannot explain from connected sources." It degrades toward *I don't know*, not toward a confident wrong answer. Use exactly this framing when a judge probes it.

**Support tickets are treated as a symptom stream, not events.** Cluster tickets by (error code / normalized issue key, cohort, day); a spike in a cluster is corroborating evidence attached to a hypothesis, not a root-cause candidate itself. This distinction (causes live in the ledger, symptoms corroborate) keeps the hypothesis space small and clean.

### 4.4 Hypothesis engine — intersection, then a scored rubric

**Candidate generation (one SQL join):** events where `ts_start` falls in `[anomaly.window.start − lookback, anomaly.window.end]` and `blast_radius ∩ anomaly.cohort ≠ ∅`.

**Scoring — five named components, each backed by a query the analyst can open:**

| Component | Question it answers | Computation (sketch) |
|---|---|---|
| **T** — Temporal | Did it start *just before* the metric broke? | 1 at onset-aligned, decaying with lag; 0 if event starts after anomaly onset |
| **C** — Cohort match | Does the blast radius *fit* the affected cohort? | Jaccard between blast-radius cohort and anomaly cohort (computed over the fact table rows each predicate selects) |
| **D** — Dose–response | Do *more-exposed* sub-cohorts hurt *more*? | Rank-correlate exposure intensity vs. impact across sub-slices (e.g. SEPA-only accounts vs. mixed-rail accounts) |
| **N** — Negative controls | Did everything that *shouldn't* have moved stay flat? | Auto-generate complement cohorts (see 4.5); N = fraction that pass |
| **P** — Learned prior | Has this event type caused this metric before? | Starts at 0.5; updated from analyst confirm/reject labels (see 4.7) |

`score = Σ wᵢ·componentᵢ` with the weights printed right on the hypothesis card. No component is an LLM opinion; all five are reproducible queries. That is the line you say to a judge when they ask "how is this not hallucination?"

### 4.5 Negative controls and effect size — the credibility layer

**Negative controls (auto-generated per candidate).** For each hypothesis, construct the cohorts its blast radius says should be *unaffected*, and check they were:

- SEPA-bug hypothesis → DACH Enterprise accounts paying by **card** should be flat. ✓
- German-macro hypothesis → **new-logo bookings** in DACH should also have dropped. ✗ (they didn't → hypothesis penalized)

This is the mechanism that kills the decoy in the demo, and it's the honest, N=1-appropriate replacement for DoWhy's "refuters."

**Effect size via difference-in-differences.** Build the counterfactual for the affected cohort from an unaffected control cohort: fit the pre-period relationship (a ratio or simple regression, e.g. DACH-SEPA renewals as a function of DACH-card + UK-SEPA renewals), project it through the anomaly window, and report `impact = actual − counterfactual` with a bootstrap interval. This is exactly what Google's CausalImpact formalizes — cite it as the production-grade upgrade, hand-roll the simple version in ~30 lines for the demo.

### 4.6 Ambiguity — the discriminating test

If `score(H1) − score(H2) < ε`, do **not** emit percentages. Instead:

1. Diff the two blast radii and find a predicate where the hypotheses predict *different* behavior (H1 says slice X moved, H2 says it didn't).
2. If such a slice exists in the data → run the query now and resolve.
3. If it doesn't (data genuinely can't distinguish) → emit the **cheapest next test**: the exact query against a system you haven't ingested, or a 24-hour experiment (e.g. re-route 5% of SEPA traffic through the old gateway), with a named owner.

Output object:

```python
DiscriminatingTest(h1="sepa_gateway_bug", h2="de_macro_budget_cuts",
    disagreement="H1 predicts card-rail DACH renewals flat; H2 predicts them down",
    test="SELECT ... WHERE payment_rail='card' AND region='DACH' ...",
    resolution_eta="instant" | "24h experiment", owner="payments-oncall")
```

No other team will have this, and it is a *direct* answer to the brief's "what does it do when the data is genuinely ambiguous?"

### 4.7 Learning loop — the compounding asset

Every diagnosis card has **Confirm / Reject / Correct** buttons. Labels land in a `diagnoses` table:

```sql
diagnoses(anomaly_id, hypothesis_id, analyst_verdict, corrected_cause, ts)
```

Round 1 story: verdicts update the per-event-type prior **P** with a simple Beta-Bernoulli update (confirmed SEPA-type causes → higher prior next time). Round 2 story: the label set becomes training data for a learned ranker, and accumulates into a company-specific library of causal priors — *"payment-gateway changes historically move enterprise renewals within 48h."* This is the moat slide: the system gets smarter with every incident, and the asset (labeled incident → cause pairs) is something no competitor and no foundation model has.

### 4.8 Narrative layer — one LLM call at the very end

A single structured-output call (Claude via the Anthropic API, `response_format` enforced with Pydantic — the `instructor` library is fine but native structured output makes it one dependency fewer). Input: the winning hypothesis, its five component scores, the control results, the effect size, the ticket-cluster corroboration. Output schema:

```python
class DiagnosisCard(BaseModel):
    headline: str                    # "SEPA gateway regression, not churn"
    causal_chain: list[EvidenceStep] # each step: claim + query_id + observed values
    effect: str                      # "-$410k MRR vs counterfactual (±$40k, bootstrap 95%)"
    rejected_hypotheses: list[RejectedHypothesis]  # each with the control that killed it
    actions: list[Action]            # owner, urgency, expected recovery basis
    open_questions: list[DiscriminatingTest]
```

The LLM is narrating verified numbers, not producing them. Every `EvidenceStep.query_id` renders as a clickable "show me" in the UI.

### 4.9 The investigator lane (added after review — how the LLM earns its slide)

Four LLM roles, all additive to the deterministic spine:

1. **Rich context extraction** (existing normalizer, expanded): beyond filling the event schema, it extracts entities, signal type ("payment latency"), and a *suggested* relationship ("deployment → latency") used only as narrative color — never scored.
2. **Proposed tests**: given the anomaly and top hypotheses, the LLM proposes up to ~6 additional checks — but only by filling a fixed template vocabulary (`compare_cohort`, `check_metric_in_cohort`, `check_symptom_lift`, `check_temporal_order`) with parameters validated against the known dimensions. The deterministic engine executes them; results render in an "AI-proposed checks" table. The rule-based controls still solely determine the N score, so the acceptance tests stay deterministic. The rules cover the checks you anticipated; the LLM covers the ones you didn't.
3. **Unverifiable causes**: a visually separate panel — *"Possible causes we cannot verify with connected data"* — where the LLM lists explanations outside the ledger (competitor move, macro shift), each with the data source that would be needed to test it. This is the honest answer to "what if the real cause was never recorded?"
4. **Evidence-grounded narration** (existing).

**Bounded exploration loop.** When no candidate clears the score floor, that is a *result* ("nothing connected explains this"), not a failure — but before reporting it, an auto-run, budget-capped exploration pass (≤ ~12 queries) may propose new slices to test or alternative control comparisons via the same template vocabulary. Everything it finds re-enters the standard verification machinery and renders labeled *Exploratory*. No open-ended agent, no free-form SQL.

**Detection is advisory, not gating.** The analyst can point the pipeline at any metric/slice/window manually from the UI sidebar; the downstream chain doesn't care where the focal anomaly came from. This converts every detection blind spot (slow drifts, ratio metrics, interaction effects) from "the system is blind" into "the system doesn't auto-surface this, but diagnoses it fine once pointed at it."

---

## 5. Tech stack (final)

| Layer | Choice | Replaces | Why |
|---|---|---|---|
| Language / API | Python 3.12 + FastAPI (only if you expose an API; the demo can be Streamlit-only) | LangGraph orchestration | Your home turf; the pipeline is 6 functions, not an agent graph |
| Analytics store | **DuckDB** (single file, also holds the ledger + labels) | DuckDB + Neo4j + Qdrant | One dependency does metrics, events, and joins; nothing to deploy |
| Stats | `statsmodels` (STL), `numpy/scipy` (MAD, bootstrap, rank corr) | DoWhy, CausalImpact lib | ~150 lines of transparent stats you can defend line-by-line |
| Schemas / validation | **Pydantic v2** | Instructor (optional) | Same guarantee, fewer moving parts |
| LLM | Claude API, structured outputs, exactly 2 call sites (event normalizer, narrator) | LLM everywhere | Contains hallucination surface to the edges |
| UI | **Streamlit** | custom React dashboard | A credible analyst UI in ~2 hours; records beautifully for the video |
| Data | Synthetic generator script (see §6) | "assume enterprise integrations" | You control ground truth → you can *prove* the ranking is right on camera |

Everything runs locally with `pip install duckdb statsmodels pydantic streamlit anthropic`. No Docker, no services, no keys except the LLM.

---

## 6. Demo data plan — engineered for the rejection moment

Generator script (`gen_data.py`) produces ~18 months of daily data:

- **Dims:** region {DACH, UK, FR, US, APAC, Nordics} × segment {Enterprise, Mid, SMB} × payment_rail {sepa, card, invoice} × product {A, B, C}.
- **Metric:** `mrr_renewals` with weekly seasonality, end-of-quarter spikes, gaussian noise, mild trend.
- **Injected incident (ground truth):** from Aug 3, renewal success for `DACH × Enterprise × sepa` drops ~85% (gateway timeout). Net aggregate effect ≈ −8%.
- **Decoy #1 (the star of the video):** DACH marketing spend cut the *same week* — but its blast radius is `new_logo_acquisition`, not renewals. Correlated in time, wrong cohort → killed by **C** and **N**.
- **Decoy #2:** unrelated US pricing change → killed by cohort mismatch instantly.
- **Event streams:** ~8 deploys (one is the SEPA gateway release tagged region=DACH-cluster, rail=sepa), 3 campaigns, 2 flag changes, ~50 Zendesk tickets (a post-Aug-3 cluster with `ERR_SEPA_504`, DACH enterprise accounts), ~20 Slack messages (one ops alert, rest noise).

Because ground truth is known, the video can show the system ranking the true cause #1 *and* explicitly rejecting the marketing decoy with the control that killed it — the moment a judge remembers.

---

## 7. One-day build plan (~12 focused hours)

| Hours | Deliverable |
|---|---|
| 0–2 | Repo scaffold; `gen_data.py` writes metrics.parquet + event/ticket/slack JSONs |
| 2–4 | Anomaly engine: MAD/STL residuals, hierarchical drill-down, contribution; unit-test against injected ground truth |
| 4–5.5 | Ledger: `ChangeEvent` schema, deterministic connectors for deploys/flags/campaigns; LLM normalizer for Slack + ticket clustering |
| 5.5–8 | Hypothesis engine: candidate join, five-component scorer, auto negative controls |
| 8–9 | Diff-in-diff effect size + bootstrap interval |
| 9–10.5 | Narrator call + Streamlit: anomaly card → treemap → hypothesis cards → confirm/reject buttons |
| 10.5–12 | Script and screen-record the 3-min video around the decoy rejection; export stills for the deck |

Cut-line if behind: drop dose–response (D) and the Slack normalizer; the demo still lands with T/C/N scoring and ticket clusters.

---

## 8. Mapping to Round 1 deliverables

**Slide 1 — The gap.** Dashboards say *what*; the *why* takes an analyst days across Slack/Jira/Zendesk — and the expensive failure mode is acting on the wrong why (cutting marketing when checkout was broken). One stat, one anecdote, no stack names.

**Slide 2 — The idea.** The pipeline diagram from §3, simplified to five boxes: *anomaly → change ledger → intersection → negative controls → narrated diagnosis with next test*. Tagline: **"Every claim is a query."** Mention exactly three mechanisms by name: Change Ledger, blast radius, negative controls.

**Slide 3 — Why it matters.** The analyst stays in the loop (drafts the investigation, human approves); target metrics stated *with their measurement method* ("top-ranked hypothesis matches analyst's final RCA in >70% of incidents, measured by replaying 12 months of postmortems"); the learning loop as the compounding moat; one line on Round 2 extensions.

**Video beats (3:00).**
- 0:00–0:30 — red dashboard, the pain, the wrong-why anecdote.
- 0:30–1:00 — the idea in one diagram; "root cause = anomaly ∩ change ledger, verified by controls."
- 1:00–2:15 — live run: drill-down finds DACH×Enterprise×SEPA; ledger surfaces 3 candidates; **camera lingers on the marketing decoy being rejected** (cohort mismatch + failed control shown on screen); diagnosis card with actions.
- 2:15–3:00 — ambiguity handling (discriminating test card), learning loop, close on "from finding out to finding it first."

---

## 9. Anticipated judge questions (and the honest answers)

- **"Isn't this just correlation?"** — Yes, plus the three things that make correlation actionable at N=1: temporal precedence, cohort-fit, and negative controls with a counterfactual baseline. We *deliberately* don't claim causal inference; we claim ranked, auditable evidence and the test that would settle it. (Saying this out loud earns trust.)
- **"What if the real cause isn't in the ledger?"** — If no candidate clears the score floor, the system says exactly that, reports which source systems are ingested vs. not, and recommends widening ingestion. Silence about unknown-unknowns is how the old design hallucinated; naming them is a feature.
- **"Cold start?"** — Deploys, flags, campaigns, and pricing diffs are deterministic connectors from day one; the learned prior starts flat and only sharpens ranking, never gates it.
- **"Where is the AI doing the hard reasoning?"** — It reads the messy human context, proposes what to investigate, decides which checks would separate competing explanations, names causes outside the connected data, and writes the diagnosis. What it never does is decide the verdict — because a root cause a model asserts is a root cause nobody can check. Every team here can build an AI that produces an explanation; the hard part is producing one a CFO will act on.
- **"Why no knowledge graph / embeddings?"** — Blast-radius predicates are the 20% that delivers 80% deterministically. Graphs earn their place in Round 2 (below) for genuinely multi-hop links.

## 10. Round 2 extension path (so nothing you researched is wasted)

- **Multi-hop supply chains:** supplier → component → product links are where a real graph (and cognee-style extraction) earns its keep; blast radius becomes *derived* by traversal instead of declared.
- **Semantic ticket clustering:** swap exact error-code keys for embedding clusters (then Qdrant is justified).
- **CausalImpact proper** for effect sizes with seasonality-aware Bayesian counterfactuals.
- **Learned ranker** over the accumulated label set; publishable precision@1 numbers from postmortem replay.
- **Write-back actions:** open the Jira rollback ticket / draft the customer-success email from the diagnosis card.
- **Learned baseline detection:** replace rolling-median/STL with a forecasting counterfactual (BSTS/Prophet with holiday + calendar-event regressors) — still reproducible and auditable, handles multiple seasonalities, gives credible intervals instead of a hand-set threshold.
- **Masking coverage:** scheduled level-1 (per-region) detection alongside the aggregate, so offsetting moves (DACH −30%, APAC +30%) that cancel at the root still surface.
