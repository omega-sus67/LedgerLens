# Demo Video — Narration Script

**Timed against the actual recording:** `LedgerLens_demo.mp4`, **5:45**, 1600×1000, silent
screen capture. Every timestamp below was read off that file frame by frame, not planned —
so you can narrate straight over it without touching the picture.

Delivery: **~150 words per minute**. Each beat carries a word budget; staying inside it is
what keeps you in sync. Where a beat runs long the picture holds still, so you have room
rather than pressure.

Figures are guarded by [`tests/test_demo_script.py`](../tests/test_demo_script.py) against a
live diagnosis. **If the app and this script disagree, the suite goes red before you record.**
Run [`demo_preflight.py`](../demo_preflight.py) first.

---

## The through-line

Say this in the first fifteen seconds and return to it in the last fifteen. Everything
between is evidence for it:

> **Every tool in this category searches your data for the answer. The answer usually isn't
> in your data — it's in your change log. We search that instead, and then try to prove
> ourselves wrong.**

The three moments that win this: **the decoy dying (1:01)**, **the model proposing but not
deciding (2:02)**, and **the refusal (4:20)**.

---

## Beat 1 — The wedge (0:00–0:30) · ~71 words

**On screen:** headline, four metric tiles, seasonality line.
**Point at:** the headline, then the four tiles left to right.

> "A dashboard tells you renewals fell eight percent. It can't tell you *why* — and that
> question costs an analyst three days.
>
> Here's what this category gets wrong. The cause of a metric movement is almost never in
> the metric's own table. It's in your change log. So we search that instead — then try to
> disprove what we find.
>
> A hundred and twenty-two thousand daily facts. Ninety-nine slices. Eighteen months."

> **Technique —** Framing. The scale line is four seconds that permanently retires the
> "is this a toy?" question.

## Beat 2 — Decomposed, then drilled (0:31–1:00) · ~63 words

**On screen:** the Attribution table.
**Point at:** the seasonality line, then the `◀ focal` row on the bottom line of the table.

> "Down eight-point-three percent. Nine-tenths of that is ordinary August seasonality —
> measured from the same cohort a year earlier, not assumed. So the number that matters is
> the remaining seven-point-five.
>
> Then it narrows to the smallest slice carrying the damage. DACH, Enterprise, SEPA. Down
> eighty-five percent. Four hundred sixteen thousand dollars — ninety-five percent of its
> parent's shortfall.
>
> Three slices out of ninety-nine."

> **Technique —** Statistics and SQL. Robust MAD-z on a frozen Theil–Sen baseline, with
> Benjamini–Hochberg across drill levels — the `BH` column. Robust estimators *because* a
> mean-based detector lets the outlier inflate its own definition of normal.

## Beat 3 — The decoy dies ★ (1:01–1:40) · ~101 words

**The forty seconds that win this. Slow down.**
**On screen:** the rejected card and its five-rule control table.
**Point at:** the red REJECTED banner → the **N** bar sitting at zero → the pink R2 row.

> "Now the one that matters. Marketing cut DACH spend one day *before* renewals broke.
> Temporally more plausible than the truth. A correlation ranker puts it first.
>
> We try to kill it instead. If this were a region-wide demand shock, nothing spares
> Mid-market and SMB on the same rail — so the engine predicts they dropped too.
>
> They came in flat. Minus one-point-three percent.
>
> That's a decisive failure. **N** goes to zero. The candidate isn't ranked second — it's
> *rejected*. A decoy still on the list is one an executive might act on.
>
> The winner survived all four controls. Point seven hundred."

> **Technique —** Business rules. Five named, falsifiable controls — R1 region-complement,
> R2 segment-siblings, R3 geo-complement, R4 objective-mismatch, R5 temporal-placebo. A rule
> you can *name* is one a domain expert can argue with. A learned weight isn't.

## Beat 4 — Innocent here, guilty there (1:41–2:01) · ~55 words

**On screen:** the evidence chain, then Recommended actions.
**Point at:** the `[P2]` action and the `basis:` query id beneath it.

> "And here it stops being a filter and becomes a product.
>
> The campaign didn't cause *this*. But the controls found it did exactly what it was
> designed to do — DACH new-logo bookings, down thirty-one percent.
>
> Cleared of this charge, convicted of another, routed to whoever owns that budget — with
> the query id underneath."

> **Technique —** Business rules. R4 objective-mismatch produces both findings from a single
> check. Every action carries `basis:` — a replayable query, not an assertion.

## Beat 5 — The model proposes, the engine disposes ★ (2:02–2:35) · ~83 words

**On screen:** the 🤖 investigator lane — proposed-checks table, then unverifiable causes.
**Point at:** the `verdict` column → the "accepted / rejected by validation" line → the
`query_id` column.

> "Now the AI — and note where it sits. *Below* the verdict, not above it.
>
> The model reads the anomaly and the controls already run, and proposes further checks. But
> only by filling a fixed template vocabulary. It doesn't write SQL. *We* execute these, and
> the results stand regardless of what it expected.
>
> Read the denominator: five accepted, one rejected by validation. That one named a dimension
> that doesn't exist. It never became a query.
>
> Every accepted check carries a replayable query id."

> **Technique —** LLM, proposing only. The validation gate runs *before* execution. Proposed
> checks are built `decisive=False` and never reach `controls.score_n` — a test asserts every
> score is byte-identical with this lane on or off.

## Beat 6 — Two guards, not one ★ (2:36–3:00) · ~67 words

**On screen:** the unverifiable-causes panel, then back to the headline.
**Point at:** the "would need / would test" lines, then the headline itself.

> "It also lists causes the connected data *cannot* test — each naming the feed that would
> settle it.
>
> And that headline was written by the model. It passed two guards: every figure appears in
> the verified payload, and it makes no causal claim this engine doesn't make. One invented
> digit and the whole narration is discarded.
>
> **The model writes the prose. Never the numbers. Never the verdict.**"

> **Technique —** LLM behind deterministic guards. This is the beat that answers *"the LLM
> must not be the source of quantitative truth"* — enforced in code, not requested in a prompt.

## Beat 7 — One computation, three readers (3:01–3:23) · ~55 words

**On screen:** CFO headline (3:01–3:11), then On-Call headline (3:12–3:23).
**Point at:** each headline as it changes. **Do not touch Growth here** — that is beat 8.

> "Same evidence, different readers. The CFO gets dollars and forecast risk — and an
> *escalation*, never an instruction to roll back a release, because they don't hold that
> lever. On-call gets the event id and the rollback.
>
> These aren't three analyses. It's one computation rendered three ways — and the query ids
> underneath are identical."

> **Technique —** Deterministic rendering. Persona sits downstream of every query and
> structurally cannot reach one. Decision rights are mechanical, not cosmetic.

## Beat 8 — Redaction that names itself (3:24–3:51) · ~73 words

**On screen:** Growth Marketing — the 🔒 banner, and changed numbers.
**Point at:** the banner's policy id → the focal cohort → the headline percentage.

> "Growth is a different question — not a different voice, a different *entitlement*. Their
> contract withholds the payment-rail cut, so the drill-down never sees it.
>
> The analyst saw DACH Enterprise SEPA, down eighty-five. Growth sees DACH Enterprise product
> A — down thirty-five. Smaller because their cut is shallower, *not* because the engine
> failed.
>
> And the card says so, naming the policy and quoting its reason. Ranked order identical.
> Entitlement hides cuts, never candidates."

> **Technique —** Business rules, enforced at exactly one chokepoint. And the banner never
> *counts* what it hides — that would mean computing the answer the reader isn't entitled to.

## Beat 9 — It declines to detect (3:52–4:19) · ~73 words

**On screen:** `payment_success_rate` — the banner sits **above** the title.
**Point at:** the banner → the pre-filled window controls → the ratio caption under
Attribution. **Don't scroll into the hypothesis list on this KPI.**

> "Third KPI, deliberately broken. It launched in June — fifty-six days of history against a
> hundred-and-twenty-day warmup. So detection *declines before it looks at a single value*,
> and says why.
>
> It's also a rate, and rates aren't additive — stored as two metrics, aggregated as a
> weighted ratio, drill-down switched off rather than shown wrong.
>
> But declining to detect isn't declining to help. Give it a window and the whole chain still
> runs."

> **Technique —** Statistics plus contract rules. The warmup gate is a threshold in the KPI
> contract, not a constant in the engine. No seasonality is claimed: this KPI has no prior
> August.

## Beat 10 — When it doesn't know, it says so ★ (4:20–4:51) · ~83 words

**On screen:** abstention headline (4:20–4:37), then the diagnosis text (4:38–4:51).
**Point at:** the headline → the connected / not-connected source list.

> "Last one, and the one I'd want you to remember. Simulate the deploy connector never having
> been wired up.
>
> The change that caused this was never in the ledger, so the system **refuses to name a
> cause**. Closest candidate: zero-three-eight, against a floor of zero-four-five. It names
> what's connected, what isn't, and what to connect next.
>
> The true cause isn't demoted — it's gone entirely. And the decoy is *still rejected*.
>
> It degrades toward 'I don't know', never toward a confident wrong answer."

> **Technique —** Deterministic set logic, applied at candidate generation. Filtering later
> would model *"we saw it and dismissed it"* — a different and less honest scenario.

## Beat 11 — A prior you can delete (4:52–5:09) · ~47 words

**On screen:** the top hypothesis after a 👍.
**Point at:** **the score** — it reads `0.708`, not `0.700` — then the **P** component.

> "An analyst confirms it — watch the score move. Seven hundred to seven-oh-eight.
>
> **P** is counted from verdict rows. Nothing trained, nothing to drift — delete the row and
> the prior returns exactly where it was. Weighted five percent: it sharpens a ranking, never
> overturns a control."

> **Technique —** Statistics — Beta–Bernoulli, derived from rows rather than kept as state.
> That `0.008` shift is the entire influence this loop is permitted.

## Beat 12 — The split, precisely (5:10–5:45) · ~99 words

**On screen:** ⏱ Telemetry — four tiles, the stage table, the *LLM vs non-LLM* paragraph.
**Point at:** "Queries executed 89" → "Replayable on this card 22" → the LLM cost tile.
*Read the counts off the screen; they move as features land.*

> "So here's the accounting — on the page, not in a slide.
>
> Everything that produced a *number* is SQL, set intersection, named business rules and
> robust statistics. Eighty-nine queries; twenty-two replayable from this card. No traditional
> ML — with one incident there's no training set. And no causal inference claimed: these are
> negative controls. They falsify. They don't estimate.
>
> The model proposed checks and wrote the prose — half a cent — and changed none of the
> numbers above.
>
> Dashboards tell you what moved. This tells you why, tries to prove itself wrong first, and
> shows you the receipt."

> **Technique —** The whole map, out loud. See the table below and name each one.

---

## Technique map — what is used where, and why

The brief is explicit: *"The LLM should not be treated as the source of quantitative truth.
Teams should explicitly demonstrate when they use deterministic logic, SQL, business rules,
statistics, traditional ML, causal inference, retrieval or LLMs — and why."* Every row below
is verifiable in the source.

| Technique | Where it is used | Why this and not something else |
|---|---|---|
| **SQL** | `Store.q()` is the only path to the database — drill-down, every control, freshness, the learned prior | Each query is hashed to a `query_id` and logged, so any number on screen can be re-run by the reader |
| **Deterministic set logic** | Candidate generation: `blast_radius ∩ cohort ≠ ∅`, as predicate intersection | The link is *already recorded* in change metadata. Set intersection is exact and explainable in a sentence; a graph traversal or embedding search is neither |
| **Business rules** | Five named negative controls (R1–R5), the `SEGMENT_AGNOSTIC_EVENT_TYPES` mechanism gate, and the contract's access policy | Each encodes a falsifiable mechanism assumption. A rule you can name is a rule a domain expert can argue with |
| **Statistics** | MAD-z detection (0.6745 scaling), Theil–Sen frozen pre-window baseline, Benjamini–Hochberg per drill level, Jaccard for **C**, Spearman ρ for **D**, Beta–Bernoulli for **P** | Robust estimators, chosen because the thing being hunted is the outlier that would corrupt a mean-based one |
| **Traditional ML** | **None. Deliberately.** | One incident is N=1 — there is no training set, and a fitted model would be unauditable exactly where a printed rubric is not. A choice, not a gap |
| **Causal inference** | **Not claimed.** Negative controls *falsify*; they do not estimate effects. `effect.py` (diff-in-diff + bootstrap CI) is specified and deliberately unbuilt | With a single incident there is no population to estimate over. The card says it ranks evidence, and shows no interval because none is computed |
| **Retrieval** | Change-ledger lookup by declared predicate; ticket clustering for corroboration | Retrieval over *recorded structured events*. No embeddings: the linkage exists in metadata and needs no inferring |
| **LLM** | Three additive sites — proposed checks from a fixed vocabulary, unverifiable causes, persona prose | The model proposes; the engine disposes. Enforced in code (`decisive=False`, never passed to `score_n`), and asserted by a test |

---

## The 3:00 cut

Drop beats **6** and **11**, and shorten **12** to its final sentence. Runtime ≈ 3:05.

You lose the second guard, the learning loop and the cost accounting. **Do not cut beats 3,
8, 9 or 10** — those are the four rubric rows nothing else on camera covers.

---

## Verified figures

`tests/test_demo_script.py` parses this table and asserts every row against a live diagnosis.
**Edit the app, not this table** — if a value stops matching, the suite fails and names the
beat to re-record.

| key | value | appears in |
|---|---|---|
| `root_delta_pct` | -8.3 | beat 2 |
| `seasonal_pct` | -0.9 | beat 2 |
| `focal_delta_pct` | -85.2 | beats 2, 8, 10 |
| `focal_delta_abs` | 416144 | beats 2, 8 |
| `candidate_count` | 5 | beat 3 |
| `top_event` | deploy_sepa_v214 | beats 3, 9 |
| `top_score` | 0.700 | beat 3 |
| `top_controls_passed` | 4 | beat 3 |
| `decoy_event` | campaign_dach_cut | beats 3, 4 |
| `decoy_score` | 0.322 | beat 3 |
| `decoy_control_flat_pct` | -1.3 | beat 3 |
| `second_finding_pct` | -31.0 | beat 4 |
| `growth_focal_delta_pct` | -34.6 | beat 8 |
| `growth_focal_delta_abs` | 207545 | beat 8 |
| `growth_top_score` | 0.627 | beat 8 |
| `redaction_policy` | fin.rail_detail | beat 8 |
| `redaction_dim` | payment_rail | beat 8 |
| `abstain_closest_score` | 0.38 | beat 10 |
| `abstain_floor` | 0.45 | beat 10 |

**Deliberately not pinned here:** the telemetry absolutes (89 / 41 / 22) and every duration.
`docs/telemetry_decisions.md` is explicit that the *ratio* is the durable point and the
absolutes move whenever a feature adds a query; a test enforces their exclusion. Read them
off the screen in beat 12.

**Note on beat 11:** the score reads `0.708` there, not `0.700`. That is the 👍 moving P from
0.50 to 0.67 — `0.05 × 0.17 ≈ 0.008`. It is the learning loop working, and it is the exact
sensitivity `CLAUDE.md` warns about when a stray verdict is left in the database.

---

## If something goes wrong on camera

| Symptom | Cause | Fix |
|---|---|---|
| Preflight fails on a figure | Data regenerated, or engine changed | Re-run `gen_data`, then `pytest tests/test_demo_script.py`, re-record the named beat |
| AI panels absent | `GEMINI_API_KEY` unset | Preflight catches this; export and restart Streamlit, not just the browser |
| Lane failures show `HTTP 503` | Gemini overloaded — transient | `llm.py` retries once; if it still fails, wait a minute and re-take |
| Red "prose was discarded" banner | A guard fired | **Keep the take.** Narrate it — a guard that visibly catches something is worth more than one that never does |
| Prior already above `0.50` | Leftover verdicts | Re-run the preflight, which clears them |
| Control table missing in beat 3 | CFO or Growth persona selected | Switch to Revenue Analyst or Payments On-Call |
| Growth numbers match analyst | Persona didn't change | Confirm **Growth Marketing**; look for the 🔒 banner |
