# Reachable Abstention — Decisions

What Task 7 built and why. Read this before changing `hypothesis.candidates`,
`narrate._connectivity`, or the source-drop toggle.

**Hardens Minimum Prototype Expectation row 5** — *"One low-confidence scenario in which
the engine requests clarification or abstains."* Row 5 already closed via Task 3's
sparse-history KPI, which declines to *detect*. This is the other half: a KPI that
detects fine and then refuses to *explain*, because the evidence is not there.

Companion docs: [`roles_decisions.md`](roles_decisions.md),
[`telemetry_decisions.md`](telemetry_decisions.md),
[`contracts_decisions.md`](contracts_decisions.md).

---

## 1. The problem this solves

`_no_cause_card()` has existed since the first build and is one of the better-written
things in the repo. It was also unreachable: on the demo data the true cause always
scores 0.700 against a 0.45 floor, so the honest branch could only be seen by editing
source. **The single most important claim this product makes — "when it doesn't know, it
says so" — was the one claim nobody could watch happen.**

A sidebar switch now simulates the deploy connector never having been wired up.

## 2. The measurement

Taken before implementing, and it matches what ships:

| | full ledger | github dropped |
|---|---|---|
| candidates | 5 | 2 |
| ranked | `deploy_sepa_v214` **0.700** … | `flag_sepa_retry_beta` **0.383** |
| rejected | `campaign_dach_cut` | `campaign_dach_cut` |
| clears floor (0.45)? | **yes** | **no → abstains** |

The plan flagged one risk: dropping `github` also removes the other eight deploys, so
does the campaign decoy win by default? **It does not.** It is still rejected by its own
segment-sibling control, at 0.322. That is the load-bearing result — a decoy that got
promoted the moment competition was removed would mean the control had never been doing
the work. `test_the_decoy_is_still_rejected_not_promoted` pins it.

## 3. Decisions

**D1 — Filter at candidate generation, not as a score penalty.**
`drop_sources` is applied inside `hypothesis.candidates()`, before anything is scored.
An unconnected system does not produce a badly-scoring candidate; it produces **no rows
at all**. Penalising a score later would model a different and less honest scenario —
one where we saw the change and dismissed it — and would leave `deploy_sepa_v214`
visible on the card as a rejected hypothesis, which is precisely the wrong story.
`test_the_true_cause_is_not_merely_demoted_but_absent` asserts it is gone from
`ranked`, from `rejected`, and from the evidence.

**D2 — Connectivity is read off the contract's lineage. This fixed a real bug.**
`_no_cause_card` hardcoded two prose strings:

```python
connected = "deploys (github), feature flags (launchdarkly), campaigns (calendar), ..."
missing   = "CRM/opportunity data, competitor pricing, macroeconomic indicators, ..."
```

With the simulation running, the card printed **"Connected sources: deploys (github)…"**
while the entire premise on screen was that github was *not* connected — the card
contradicting the demo, in the one branch whose whole purpose is honesty about what we
do not have. That is the class of error this repo exists to avoid, and it would have
been found on stage.

Connectivity now comes from `contract.lineage` (steps of kind `context`/`symptom`) minus
`payload.drop_sources`. The "no feed exists" list comes from
`contract.anticipated_event_types`, which Task 1 declared for exactly this purpose.
`test_the_connected_list_is_read_off_the_contract_not_hardcoded` fails if a connector is
added to a contract and the card does not mention it.

**D3 — Display labels stay local; connectivity claims do not.**
`SOURCE_LABEL` maps `github → "deploys (github)"` and lives in `narrate.py`. That is
cosmetic: *which* sources exist and *whether* they are connected is the contract's job.
Keeping the two apart is the point — a label that drifts is a typo, a connectivity claim
that drifts is a lie.

**D4 — The P1 action names the dropped source.**
The old action said *"Connect CRM/opportunity data, competitor pricing, macroeconomic
indicators…"* — a wish. With a source simulated away it now says **"Connect github so
the next incident of this shape has candidates to test"** — a ticket somebody can close.
With nothing dropped it falls back to the standing gap, which is still the honest ask.

**D5 — `drop_sources` joins the cache key, for the third time and the last.**
`load_payload` now keys on `(metric, as_of, cohort, window, role, drop)`. Same reason as
Task 4's `role`: removing a source removes candidates, which changes the payload.
`test_toggling_the_drop_back_off_restores_the_diagnosis` guards it. Task 5's feedback
would be the fourth input and goes in the same signature — the debt is now paid in a
shape that scales rather than re-litigated per task.

**D6 — The toggle is a labelled simulation, never a silent one.**
The checkbox says *"Deploy source (github) not connected"*, its help text explains that
candidates are removed at generation, and a sidebar caption appears while it is on. The
card must never look like it broke; it must look like it is short of evidence. This is
the same principle as Task 4's redaction banner: **a system that shows less must say why
it is showing less.**

**D7 — `frozenset`, not `set`.**
Defaults are shared across calls, and a mutable default that some caller mutates would
silently change every later diagnosis. `frozenset()` as a default argument is safe by
construction.

## 4. What was built

| File | Change |
|---|---|
| `ledgerlens/hypothesis.py` | `candidates(..., drop_sources)`, `rank(..., drop_sources)`. |
| `ledgerlens/pipeline.py` | `diagnose(..., drop_sources)` and `run(..., drop_sources)`; carried onto the payload. |
| `ledgerlens/narrate.py` | `NarrationPayload.drop_sources`; `SOURCE_LABEL`; `FEED_FOR_ANTICIPATED`; `_connectivity()`; `_no_cause_card` uses all three. |
| `app.py` | "Simulate a gap" sidebar section; `drop_key` in the cache key. |
| `tests/test_abstention.py` | 9 tests. |
| `tests/test_app.py` | 2 tests — the toggle works, and toggling back restores. |

**Test count: 218 → 229.**

## 5. What the demo gets

A beat that was previously only assertable in prose:

> "Disconnect the deploy feed — as if nobody had wired that connector up. The anomaly is
> still real, still −85%, still $416k. But the change that caused it was never in the
> ledger, so the engine has nothing above its floor. It does not guess. It tells you the
> closest thing it found scored 0.38 against a 0.45 floor, it tells you exactly which
> feed it is missing, and it gives the data-platform team a ticket. That refusal is the
> product."

Pairs directly with the telemetry panel's closing line: *and when it doesn't know, it
says so — for $0.0000 per diagnosis.*

## 6. What this deliberately is not

- **Not a real connector health check.** Nothing probes whether github is actually
  reachable. This simulates absence; it does not detect it. A production version would
  read connector status and drop sources automatically — named in the roadmap.
- **Not per-event suppression.** The switch drops a whole *source*, not individual
  events. Dropping one event would be a different and less honest scenario: it is
  cherry-picking, not a missing feed.
- **Not wired to freshness.** `contracts.freshness()` already measures per-source lag and
  could in principle drive this automatically ("this feed is 9 days stale, treat it as
  absent"). That is a genuinely good next step and is deliberately not in this cut.
