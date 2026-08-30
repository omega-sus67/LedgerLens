# Post-Work — Decisions

Covers the submission-hardening pass of **2026-08-30**: four additions to the business
proposal, a rewritten demo script with a machine-checked figures table, a drift test and a
pre-flight. Same contract as every other record in this directory — what was built, what
was deliberately *not* built, and the reasoning behind each choice a later reader might
otherwise undo.

**Nothing in `ledgerlens/` or `app.py` was touched.** This pass is documentation, one test
file and one operational script. That was a constraint, not an outcome: the deadline is the
same day, and the engine had 307 passing tests against it.

---

## 1. What prompted this

A review of the repo against its own submission found the engineering far ahead of its
presentation. Three specific gaps:

- The business proposal answered every question the brief asked and **not** the question a
  judge actually asks — *why not ThoughtSpot, Sisu, or Databricks Genie?*
- **Two of the ten Minimum Prototype Expectations had no on-camera moment.** Row 6 (sparse
  KPI) and row 7 (role entitlement) were built, tested and documented, and appeared nowhere
  in the shot script.
- The demo's figures were verified by a human reading the screen. Every other claim in this
  repo is verified by a test.

---

## 2. Decisions — the business proposal

### D1. Competitive framing is a *wedge*, not a feature table

Added §2.8. The comparison deliberately does **not** enumerate features, because a feature
comparison against ThoughtSpot or Databricks is one this prototype loses — they have
years of surface area. It compares *where each category stops*, which is a claim about
architecture rather than maturity:

> The cause of a metric movement is almost never in the metric's own table.

Everything in the category searches the data for the answer; this searches the change log
and then tries to disprove what it finds. That distinction survives any amount of
competitor engineering, which is what makes it worth writing down. A feature table would
be obsolete the week someone ships a change-log connector.

### D2. "Why now" belongs in problem framing, not solution design

Added to §1, before *"the claim we deliberately do not make"*. It is a statement about the
world — deploy metadata, flag targeting and campaign geo became machine-readable in the
last five years — and not about the product. Putting it in §2 would read as a feature; in
§1 it reads as timing, which is what an innovation challenge rewards.

### D3. Reframed for a systems integrator, not a startup

Added §4.5 *Delivery shape*. The audience is Accenture: their business is deploying things
at clients, and a proposal written as a product pitch answers questions they were not
asking. The reframe is that **the connector mapping is the deliverable** — client-specific
configuration, not custom engineering — and the engine is a reusable asset across
engagements. Three properties carry it: no new infrastructure (it is SQL, warehouse-native),
it clears audit on the first pass because every number has a `query_id`, and it fails safely
in front of a client because it abstains rather than guessing.

### D4. The success metric that cannot be gamed by being more confident

Added §4.6. The feedback loop already collects the product's own KPI — verdicts are rows,
so confirmation rate is a query rather than a survey. The load-bearing row is the last one:

> **Abstention rate: non-zero, and monitored as a health metric.** A system that never says
> *"I don't know"* has not become more accurate — it has stopped being honest, so a falling
> abstention rate is an alarm rather than an improvement.

Stated because every other candidate metric improves when the system gets more confident,
including when that confidence is wrong. This one does not.

---

## 3. Decisions — the demo

### D5. Twelve beats at ~4:35, not nine at 3:00

The brief sets no duration. The instruction was *"sweet, but every feature must get its
deserved time"*, and two rubric rows had no beat at all. Cutting to fit 3:00 would have
meant a shorter video that closed fewer rows — the wrong trade when the runtime is not
constrained. A **3:00 cut list is included** (drop beats 6 and 11, compress 12) so one
recording produces either length, and it names beats 3, 8, 9 and 10 as uncuttable because
they are the four rows nothing else covers.

### D6. Beat 4 exists because the evidence already existed

*"Innocent here, guilty there"* — the decoy did not cause the renewals drop but **did**
drive DACH new-logo bookings down 31%, and the card already carried it as a `[P2]` action
with its own `query_id`. It was computed, rendered and unfilmed. It is the most
sophisticated fifteen seconds available and it cost nothing to add.

### D7. Persona and role get separate beats, and the script says why inline

Beat 7 flips Analyst → CFO → On-Call and **explicitly does not touch Growth**. Beat 8 is
Growth, framed as *entitlement* rather than voice.

This is the single most likely presenter error, so the warning is inline in beat 7 rather
than in a footnote. Task 4 made *"identical query ids"* false for the growth role — the
focal cohort legitimately changes, so the numbers legitimately change. Flipping to Growth
inside the persona beat would state a claim that is false for that role while true for the
other three, on camera, in the beat whose entire point is that the evidence is shared.

### D8. A "Verified figures" table is the contract between script and app

The script's prose is for a human; the table is for a test. Nineteen rows, parsed by
`tests/test_demo_script.py` and asserted against a live diagnosis. If a value drifts the
suite fails **before** recording rather than after, and the failure message names the beat
to re-record.

The near-miss that motivated the design: while drafting, an independently computed focal
share came out at **84.8%** where the card says **95%** — because the card reports the share
of the *parent node* and the recomputation used the root. **The rendered card is the source
of truth for every figure the script quotes; recomputing one is how a wrong number gets
into a script.**

### D9. Telemetry absolutes and durations are excluded, and a test enforces the exclusion

`test_the_script_never_pins_a_telemetry_absolute_or_a_duration` fails if a key matching
`quer|_ms|latency|token|cost` enters the table.

`telemetry_decisions.md` is explicit on both: the query counts (89 / 41 / 22) move whenever
a feature adds a query, so only the *ratio* is durable; and a duration must never be
asserted because cold-vs-warm is ~2.6× and fixture warmth is test-order dependent. Pinning
either would make this file go red for a reason that is not a demo problem — and **a check
that cries wolf is one people learn to skip**, which costs more than the check was worth.
Beat 12 instructs the presenter to read them off screen instead.

### D10. The test checks table-to-app, deliberately **not** table-to-prose

The prose says *"down 85%"* and *"$416,144"* where the table says `-85.2` and `416144`.
Mechanically verifying that every table value appears in the narration would require either
constraining how the script may be written or building a formatter that reproduces every
display convention — fragile, and it would fight the script's job of being readable aloud.

Instead the `appears in` column is a human-facing re-record instruction, and a test asserts
only that the beats it names **exist**. That catches the failure that actually happens — a
table row pointing at a beat someone cut — without pretending to catch one that does not.

### D11. The pre-flight does not warm the cache, and says so

An earlier draft of this pass claimed it did. It cannot: `Store._q_cache` is per-process and
Streamlit's `load_payload` is `@st.cache_resource`, so a diagnosis run in a subprocess warms
nothing the browser will use. Cache warming stays a manual browser step, printed in the
"only you can do" list.

Recorded because the claim was written before it was checked, in the one repository whose
entire thesis is that claims are checkable. **The pre-flight fixes what it can fix, reports
what it cannot, and claims nothing in between.**

### D12. The pre-flight shells out to pytest rather than importing the checks

One source of truth for the figures, and `tests/test_docs.py` already establishes
subprocess-to-pytest as the pattern in this repo. The alternative — importing the assertions
— would drift the moment someone edits the test.

### D13. It fixes the prior; it only reports everything else

Clearing stray `verdict` rows is safe, reversible and invisible on camera if skipped until
it is not. An absent API key, missing data or a locked database are reported with the exact
command that resolves each. The pre-flight does not install, generate or export on your
behalf — a script that silently regenerates data before a recording is how a seed changes
without anyone deciding to change it.

---

## 4. What was deliberately NOT done

### More synthetic data — rejected

Considered and declined. Three reasons, in order:

- **It is not thin.** 122,562 fact rows, 99 slices, 549 days, 13 ledger events across four
  connectors, three KPIs on three cadences. MPE row 1 asks for 3–5 KPIs across 2–3 sources
  at different grains; that already closes. The actual gap was that **nothing said the scale
  out loud**, which beat 1 now does in four seconds.
- **`gen_data.py` is the documented fragile component**, on the submission day itself. One
  sequential RNG stream; any new series without its own `default_rng(SEED_*)` shifts every
  downstream draw, and the failure mode `CLAUDE.md` names is *green tests, wrong demo*.
  `test_sparse_kpi.py`'s fingerprints and `test_pipeline.py`'s exact-value assertions both
  sit downstream. Task 11 was already cut partly for this reason.
- **It would weaken the pitch.** The dataset is engineered rhetoric — the decoy is
  temporally *more* plausible than the truth, which is the entire demo. A second incident
  dilutes the one clean moment and invites a question that currently never arises: *with
  several anomalies on screen, why that one?*

A second incident **of a different shape** — a gradual flag rollout rather than a
step-change deploy — would genuinely prove generality and belongs in the roadmap, not in
the last day.

### A prose-to-table consistency check — see D10

### Any change to `ledgerlens/` or `app.py`

No shipping code was modified. Every new beat films behaviour that already existed; the two
"new" rubric rows needed a camera, not a feature.

---

## 5. Files

| File | Change |
|---|---|
| [`business_proposal.md`](business_proposal.md) | +§1 *Why now*, +§2.8 competitive, +§4.5 delivery shape, +§4.6 success metrics |
| [`demo_script.md`](demo_script.md) | rewritten: 9 → 12 beats, ~4:35, + verified-figures table, + 3:00 cut list |
| [`../tests/test_demo_script.py`](../tests/test_demo_script.py) | new — 23 tests; the figures table against a live diagnosis |
| [`../demo_preflight.py`](../demo_preflight.py) | new — key, data, prior reset, figure verification |
| [`../README.md`](../README.md) | test count 307 → 330 |
| [`../CLAUDE.md`](../CLAUDE.md) | current-state test count |

Test count **307 → 330**. Per this repo's convention the README's number moved in the same
change, because `tests/test_docs.py::test_readme_test_count_is_true` fires on every change
that adds a test.

---

## 6. Things not to do to this work

- **Do not edit the verified-figures table to make the suite green.** The failure message
  says this, and it is the whole point: a red row means the app changed and a beat needs
  re-recording, or something regressed. Editing the table hides both.
- **Do not add a telemetry count or a duration to that table.** There is a test that stops
  you, and D9 is why.
- **Do not merge beats 7 and 8.** Persona and role are different axes; the claim that holds
  for one is false for the other. D7 is why.
- **Do not let the pre-flight regenerate data.** It reports missing files and stops. A
  script that reseeds before a recording is how the demo's numbers change without anyone
  deciding they should.
- **Do not cut beats 3, 8, 9 or 10 for time.** They are the four rubric rows nothing else
  on camera covers. The 3:00 cut list drops 6 and 11 instead.
