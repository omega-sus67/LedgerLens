# The Investigator Lane — Decisions

How the LLM works in LedgerLens, end to end. Read this before touching
`ledgerlens/llm.py`, `ledgerlens/investigator.py`, `config.PROVIDERS`, or the
`investigate` flag on `pipeline.diagnose`.

Companion docs: [`telemetry_decisions.md`](telemetry_decisions.md) (the panel that
reports this lane's cost), [`abstention_decisions.md`](abstention_decisions.md) (the
connectivity machinery site 3 reads), [`roles_decisions.md`](roles_decisions.md) (the
cache-key boundary this extends).

---

## 1. What was wrong

`businessintelligence-ai-redesign.md` §4.9 — *"the investigator lane (added after
review — how the LLM earns its slide)"* — specifies four LLM call sites. **None of
them had been built.** What existed was a set of sockets with nothing plugged in:

| Socket | State before this task |
|---|---|
| `config.MODEL` | dead config; `tests/test_docs.py` said so in a docstring |
| `config.LLM_TEST_BUDGET`, `EXPLORER_QUERY_BUDGET` | never read by any module |
| `Telemetry.llm_calls / llm_tokens / llm_cost_usd` | permanently `0, 0, 0.0` |
| `DiagnosisCard.generated_by: Literal["llm","template"]` | permanently `"template"` |
| `DiagnosisCard.proposed_tests`, `.unverified` | permanently `[]` |
| `models.ProposedTest`, `models.UnverifiedHypothesis` | declared, never constructed |
| `models.ExtractedSignal` | docstring: *"Output of the (unbuilt) LLM normalizer lane"* |

The practical consequence: on an **AI** innovation challenge, the telemetry panel
proudly reported **0 LLM calls, $0.0000**. The zero was a real engineering argument
and it is still made on the page — but it was the *only* thing the page said about
AI, which reads as absence rather than discipline.

The brief itself names the trap, and this document follows its instruction:

> Pitch it as **"an AI business investigator that generates and tests root-cause
> hypotheses against enterprise evidence."** Not a "causal inference engine"
> (indefensible under questioning), and not "a deterministic engine with an LLM
> narrator" (undersells it at an AI challenge).

## 2. The shape of the fix

Three call sites, all **additive to a deterministic spine**:

```
                  DETERMINISTIC (no model, ever)                    │  ADDITIVE
                                                                    │
 detect ─► drill ─► focal cohort ─► symptoms ─► candidates ─► rank  │
                                                       │            │
                                                  score T,C,D,N,P   │
                                                       │            │
                                                  controls ─► N ────┤
                                                       │            │
                                                    ranked          │
                                                       ├────────────┼─► site 2  propose_tests
                                                       │            │      LLM fills a template ─► WE run the SQL
                                                       ├────────────┼─► site 3  unverified_causes
                                                       │            │      causes outside the ledger + the feed to test them
                                                    template card   │
                                                       ├────────────┼─► site 4  narrate_prose
                                                       │            │      rewrite prose ─► numbers guard ─► accept or discard
                                                       ▼            │
                                                 DiagnosisCard      │
```

Everything left of the line runs with no API key, no network, and no vendor. That is
what the 229-test suite exercises, and it is unchanged by this task.

## 3. Decisions

### D1. The LLM proposes; the evidence disposes — and it is a mechanism, not a slogan

The load-bearing property of this whole feature is that **nothing the model returns
can change a rank**. That is enforced in three specific places, not by convention:

1. **`investigator.execute()` constructs every `ControlResult` with
   `decisive=False`.** `decisive` is the field `controls.score_n` reads to zero out
   N. A proposed check that could set it would let the model reject a hypothesis by
   asking a question.
2. **Proposed tests are never passed to `controls.score_n`.** They are attached to the
   `DiagnosisCard` after ranking is finished, by `narrate()`.
3. **The lane runs after `hypothesis.rank`** in `pipeline.diagnose`, so there is no
   code path by which its output could reach the ranker even accidentally.

`test_the_lane_cannot_change_a_single_score` asserts the consequence on scores rather
than on order — order is the weaker claim, since two candidates can swap places
without either score moving.

**Why the lane runs last, not first.** Given the engine's conclusions and the controls
already run, the model can propose checks that *attack* them. A lane that ran first
would be guessing at an anomaly nobody had characterised yet, and its output would
have to be re-verified from scratch. The prompt therefore includes every ranked
candidate, its blast radius, and every control already executed with its result.

### D2. Site 1 of the spec — the LLM event normalizer — is deliberately NOT built

§4.9 lists a fourth site: Slack messages and support tickets passed through a
structured-output call to fill `ChangeEvent`, with an *"inferred — verify"* badge and
the extraction confidence multiplied into the hypothesis score.

It is cut, and the reason is specific rather than budgetary. **That site is the only
one of the four that is not additive.** Multiplying a score by an LLM-emitted
`confidence` puts the model on the ranking path, which is exactly the property D1
exists to prevent. Building it correctly means also building the confidence
calibration, the badge, and the "reject dimension values outside the known universe"
gate as a *scoring* concern rather than a validation one.

The schema (`models.ExtractedSignal`) and the fields it would fill
(`ChangeEvent.extraction`, `.confidence`) stay declared, because they are the honest
record of a designed-and-deferred feature rather than an oversight. **If it is built
later, `extraction="llm"` events must be shown separately and must not be allowed to
outrank a `deterministic` one on confidence alone.**

### D3. Provider-agnostic, with Gemini Flash as the default

`config.PROVIDERS` is a table of `ProviderSpec` rows — model id, API-key env var, and
input/output price per MTok — and it is **the only place in the repo a vendor is
named**. `ledgerlens/llm.py` holds one adapter class per row. Nothing in
`investigator.py`, `pipeline.py`, `narrate.py` or `app.py` mentions a vendor.

Switching vendor is an environment variable:

```bash
LEDGERLENS_LLM_PROVIDER=anthropic streamlit run app.py
LEDGERLENS_LLM_MODEL=gemini-2.5-pro streamlit run app.py   # same vendor, bigger model
```

**The interface is exactly one method** — `Provider.structured(system, prompt,
schema, name) -> (dict | None, Usage, error)`. Every capability this system needs
from an LLM is "JSON matching a schema": no streaming, no multi-turn, no tool loops.
`test_the_provider_interface_is_exactly_one_method` pins that, because a second
method would necessarily describe one vendor's feature, and the investigator would
start branching on vendor from there.

**Two adapters that share no code path, on purpose.** `GeminiProvider` is hand-rolled
REST over `httpx` using `generationConfig.responseSchema`; `AnthropicProvider` is the
official SDK using forced tool-use. They have different wire formats, different
structured-output mechanisms, and different usage-accounting fields — and the
investigator cannot tell them apart. That is what makes "provider-agnostic" a
demonstrated property rather than a claim.

**Why REST rather than `google-genai`.** `httpx` is already installed as an
`anthropic` dependency, so the Gemini path adds no new dependency on submission day.
The second reason matters more: an SDK-shaped abstraction tends to leak its vendor's
concepts into the interface, which is precisely what a provider seam is trying to
avoid.

### D4. Schemas are hand-written, not derived from Pydantic

The obvious move is `SomeModel.model_json_schema()`. It does not work: Pydantic emits
`$defs` and `$ref` for nested models, and **Gemini's `responseSchema` rejects them
outright**. Gemini also names types with the proto enum spelling (`OBJECT`, not
`object`) and 400s on keys outside its OpenAPI subset — `title`, `default` and
`additionalProperties` all appear in Pydantic output and all have to go.

So there are two artifacts, and they are genuinely different concerns:

- **the wire schema** — hand-written in the portable JSON Schema subset both vendors
  accept, adapted per provider by `llm._to_gemini_schema`
- **the internal model** — `ProposedTest`, `UnverifiedHypothesis`, which validate what
  comes back

`test_no_shipped_schema_uses_a_ref` fails if a future edit reaches for the Pydantic
shortcut. `test_shipped_schemas_survive_the_gemini_adapter_intact` catches the more
insidious version, where translation silently drops a `required` field and loosens the
contract with the vendor — a bug that surfaces only as a bad answer on stage.

The adapter **drops** unrecognised keys rather than passing them through. That is the
safe direction: an unrecognised key is a 400 for the entire request, while a dropped
one only loosens validation that Pydantic re-applies on the way back in.

### D5. Site 2 — the template vocabulary and its validation gate

The model may not write SQL. It fills one of exactly four templates:

| Template | What the engine runs | Typical use |
|---|---|---|
| `compare_cohort` | `anomaly.measure(metric, cohort, focal window)` | is the blast radius right? |
| `check_metric_in_cohort` | same, on a *different* KPI | did the change hit what it should have? |
| `check_symptom_lift` | ticket volume vs its 28-day baseline, via `store.q` | did the cohort complain? |
| `check_temporal_order` | `anomaly.measure` over the N days *before* onset | did the problem predate the change? |

`params` is a **flat** object — dimension names map to arrays of values, reserved keys
(`metric`, `prediction`, `days_before`) map to scalars. That shape is not cosmetic: it
is exactly `dict[str, str | list[str]]`, the type `models.ProposedTest.params` was
already declared with, so the wire format enforces itself.

**The gate.** Every proposal passes `investigator.validate` before anything runs. Each
rejection reason below is a specific hallucination it catches, and each has a test:

- template outside the four → `unknown template`
- a dimension the business does not have → `unknown dimension`
- a *value* outside `dim_registry` → `value(s) outside the region universe`, **even
  when its siblings are valid** (`["UK", "Narnia"]` is rejected whole; partial-credit
  validation is the dangerous kind, because it would run the query with the good half
  and present an answer to a question nobody asked)
- a metric not in `contracts.CONTRACTS` → `unknown metric`
- `check_symptom_lift` against `payment_rail` or `product` → **the ticket table carries
  only `region` and `segment`.** This is not a wrong answer, it is an unanswerable
  question, so it is rejected rather than run and returned as a misleading "no tickets"
- a cohort that selects no rows, a duplicate proposal, `days_before` out of range

Validation happens **before** execution, so a rejected proposal never becomes a query.

**Rejections are counted and displayed.** `Telemetry.llm_proposals_rejected` feeds a
UI line reading *"4 accepted, 2 rejected by validation."* A validator that never
reports catching anything is indistinguishable from one that is not running, and the
denominator is a stronger claim about the system than the numerator.

**Why the results are trustworthy on the card.** An accepted check goes through
`anomaly.measure` and `store.q` — the same two functions behind every rule-based
control — so it carries a real, replayable `query_id`. `pipeline.card_query_ids` was
extended to include them, which makes an AI-proposed number exactly as auditable as
any other number on the page. That extension is a no-op when the lane is off, so no
existing telemetry figure moves.

One observed consequence worth knowing: `query_id` is content-addressed over
SQL+params, so an AI-proposed check that happens to ask a question a rule-based
control already asked **collides to the same id and dedupes**. In the reference run,
4 accepted checks raised `queries_on_card` from 19 to 22, not 23.

**On `check_symptom_lift`'s prediction direction.** Tickets go *up* when something
breaks, but `ControlResult.prediction` only has `should_be_flat` and
`should_also_drop`. Rather than add a third value — which would change a `Literal` that
`controls.decisive_failure` branches on, for a lane that must never reach it — the
template is specified as *"if this cohort was unaffected, its ticket volume should be
flat."* A spike then **fails** the check, and the failure is the evidence. In the
reference run this fires at **+2766.7%** on DACH · Enterprise, which is the most
legible single result the lane produces.

### D6. Site 3 — unverifiable causes read connectivity off the contract

The panel lists causes that live outside the ledger, each with the feed that would
settle it. The prompt is built from `contract.lineage` (minus any `drop_sources`) and
`contract.anticipated_event_types` — **never from prose typed into
`investigator.py`**.

That is not tidiness. Task 7 fixed exactly this bug in `_no_cause_card`, which
hardcoded its connectivity prose and therefore printed *"Connected sources: deploys
(github)…"* while the demo was simulating github being disconnected — the card
contradicting the demo, in the branch whose entire purpose is honesty. Retyping a
connectivity claim into a prompt would recreate it one layer up.
`test_unverified_causes_never_invent_a_connected_source` drops `github` and asserts it
is absent from the prompt's connected-sources line.

The panel renders under an explicit "Not tested" warning. An honest *"we would need
an FX feed"* is worth more here than a confident guess, and the prompt says so.

### D7. Site 4 — the numbers guard

The narrator rewrites `headline` and `summary` in the persona's voice. It is the one
place in this system where an LLM writes text a reader will believe, so it is the one
place that needs a mechanical check.

**How it works.** The template card is built **first and unconditionally**, then
optionally overwritten. `narrate._narration_corpus` renders that finished card —
headline, summary, every evidence step, the effect estimate, every ranked and rejected
candidate with its controls, every action, and the seasonal split — into the corpus
handed to the model. Then `investigator.guard` extracts every numeric token from the
returned prose and subtracts the tokens present in the corpus. **A non-empty
difference discards the narration entirely** and the template card stands.

Building the template first means the fallback needs no separate code path: it is
simply the card that already exists.

**It is deliberately strict and deliberately dumb.** The narrator is shown every
figure it may use, so a digit it emits that was not in front of it is, without
exception, invented. A rounded restatement — *"about $400k"* for `-$410,144` — trips
the guard and loses the narration. That is the correct trade: the alternative is a
tolerance window, and a tolerance window is a range inside which a wrong number is
permitted.

Normalisation strips thousands separators and trailing zeros, so `410,144` and
`410144.0` are one token while `410` and `411` stay distinct. Sign and unit are never
captured, so `-8.2%` and `8.2` are the same token — the guard's question is *"where
did this digit come from"*, not *"is the sign right"*, and the sign is prose the
template already fixed.

**Rejection is a feature, and the UI says so.** When the guard fires, the page shows
which numbers were invented and states that the deterministic template is what the
reader is now looking at: *"This is the guard working, not the system failing."*
`generated_by` flips to `"llm"` only on a clean pass.

### D8. Everything fails open, and says which failure it was

`ledgerlens/llm.py` never raises into the pipeline. No key, unknown provider, DNS
failure, timeout, non-200, unparseable body, missing tool-use block — every one
returns `None` with a reason string.

But **"the lane found nothing" and "the vendor was down" must not look the same**, so
`llm.Budget.failures` records the reason and the UI renders it. A failure records no
call, because an outage costs nothing and must not inflate the call count.

The same principle governs the disabled state: when no key is set, the sidebar
checkbox is disabled *and captioned with the env var that would enable it*
(`GEMINI_API_KEY is unset`). A greyed-out control with no explanation is the silent
degradation this product argues against everywhere else.

`config.provider_spec()` returns `None` rather than raising on an unknown provider
name, so a typo in an environment variable cannot stop the deterministic pipeline —
which does not read that setting at all.

### D9. `investigate` is the fourth cache-key input, exactly as predicted

`app.load_payload`'s docstring, written at task 4 and extended at task 7, says the
signature scales: cohort/window, then `role`, then `drop_sources`, then "task 5's
feedback would go here too." `investigate` is the fourth, and it belongs above the
payload boundary for the same reason the others do — the lane runs real queries and
puts their results on the card, and it costs money and latency to recompute.

Note the asymmetry with persona, which stays below the boundary: **the investigator
changes what is shown but provably not what was ranked.** It is above the line for
cost, not for correctness.

### D10. Telemetry carries the lane's guards, not just its cost

The new `Telemetry` fields are `llm_provider`, `llm_model`,
`llm_proposals_rejected`, `llm_guard_rejections` and `llm_failures`. They live on
`Telemetry` rather than on a new model because they are facts about the **process**,
not about the data — which is the existing carve-out that lets `Telemetry` carry no
`query_id`. **This is not a third exception to "every number traces to a query"; it is
the second one, extended.**

`_llm_telemetry` returns `{}` when the lane never ran, so the defaults stand and a
deterministic diagnosis reports *no provider* rather than *a provider that made zero
calls*. Those are different states and the panel distinguishes them.

`llm_cost_str` renders sub-cent costs at six decimal places. Gemini Flash is cheap
enough that three calls land near `$0.0096`, but a single narration call can round to
`$0.0000` at four places — and "$0.0000" on an AI challenge invites exactly the wrong
question.

`stage_ms` gains `propose` and `unverified` keys **only when those stages ran**,
following `telemetry_decisions.md` D4: a padded zero reads as "instant", an absent key
reads as "not applicable".

### D11. Narration must not bill against the cached payload

Found by a test, not by review, and worth stating because the failure was invisible on
a single render. `app.load_payload` is `@st.cache_resource`, and the payload carries
`llm_budget`. Narration originally recorded its call into that object — so **every
re-render reused the cached payload and incremented the same budget**. Switching
persona twice reported seven calls instead of three, and the figure climbed for as long
as the reader kept clicking, in the one panel whose entire job is honest cost
accounting.

`narrate()` now uses a fresh `Budget` for its own call and `llm.Budget.plus` sums the
two immutably, which makes `narrate()` idempotent against a cached payload.
`test_rerendering_does_not_inflate_the_llm_bill` switches persona twice and asserts the
count stays at three.

This is the general hazard with the mutable-accumulator design: it is the right shape
for threading one diagnosis through two modules, and the wrong shape for anything that
outlives one diagnosis. The budget from `diagnose()` is cached; the one from
`narrate()` must not be.

## 4. What the reference run produces

With the lane on (stub vendor, real engine, `mrr_renewals` at `2026-08-17`):

```
generated_by : llm
accepted     : 4 | rejected: 2
   compare_cohort              -2.2%  held    decisive=False q_fac0896594
   check_symptom_lift       +2766.7%  FAILED  decisive=False q_4925333fd6
   check_temporal_order        -0.6%  held    decisive=False q_f929ffad77
   check_metric_in_cohort     -31.0%  held    decisive=False q_41f08cf427
unverified   : 2
telemetry    : 3 calls | 14,400 tokens | $0.0096 | gemini gemini-2.5-flash
stages       : detect drill symptoms rank seasonal propose unverified narrate
on-card qids : 22   (19 without the lane)

RANK INVARIANT
  off: deploy_sepa_v214 0.7000 · deploy_dunning_v3 0.4432 · deploy_billing_ui_v9 0.3929 · flag_sepa_retry_beta 0.3833
  on : deploy_sepa_v214 0.7000 · deploy_dunning_v3 0.4432 · deploy_billing_ui_v9 0.3929 · flag_sepa_retry_beta 0.3833
  identical ✓
```

The two rejections were a hallucinated region (`Wakanda`) and an attempt to escape the
template vocabulary (`run_sql`). Both were caught before any query ran.

## 5. Files

| File | Role |
|---|---|
| `config.py` | `PROVIDERS` table, `provider_spec()`, budgets, timeouts. The only vendor names in the repo. |
| `ledgerlens/llm.py` | Transport. `Provider` protocol, `GeminiProvider`, `AnthropicProvider`, `Budget`, `resolve()`. The only module that imports a vendor SDK or calls an API. |
| `ledgerlens/investigator.py` | The three sites, the template vocabulary, the validation gate, the numbers guard. |
| `ledgerlens/pipeline.py` | Sites 2 and 3, after ranking, behind `investigate`. |
| `ledgerlens/narrate.py` | Site 4, the corpus builder, telemetry fold. |
| `app.py` | Sidebar control, the two panels, the LLM-vs-non-LLM copy. |
| `tests/test_investigator.py` | 36 tests. The rank invariant, the gate, every template, the guard. |
| `tests/test_app.py` | 8 added. The panels, the disabled state, the widget order, and the re-render billing regression. |
| `tests/test_llm.py` | 19 tests. The seam, the schema dialect, resolution, pricing. |

## 6. Things not to do to this code

- **Do not let a proposed check set `decisive=True`**, and do not pass
  `card.proposed_tests` to `controls.score_n`. That single boolean is the mechanical
  form of D1.
- **Do not derive the wire schemas from Pydantic.** See D4; there is a test.
- **Do not add a second method to `Provider`.** See D3; there is a test.
- **Do not retype a connectivity claim into a prompt.** Read it off the contract. See
  D6; there is a test.
- **Do not loosen the numbers guard into a tolerance window.** See D7. If the narrator
  needs a figure it does not have, add that figure to `_narration_corpus` deliberately.
- **Do not name a vendor outside `config.PROVIDERS` and `ledgerlens/llm.py`.**
- **Do not record a narration call into `payload.llm_budget`.** See D11.
