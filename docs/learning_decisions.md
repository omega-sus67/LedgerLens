# The Feedback Loop — Decisions

Round 2 Objective 7: *"mechanism to learn from analyst and business-user feedback."*
Read this before changing `ledgerlens/learning.py`, `Store.invalidate`, or the P
component.

Companion docs: [`ai_decisions.md`](ai_decisions.md), [`roles_decisions.md`](roles_decisions.md).

---

## 1. What was there

`learning.prior()` was live and already fed the **P** score through
`hypothesis.py`. `learning.record()` was written. The `verdict` table was in the schema.
**Nothing called `record()`** — the loop was open, and the module docstring said so:
*"`record` exists so the UI can close the loop when the confirm/reject controls are
built."*

## 2. Decisions

### D1. Count rows at read time; keep no model state

Alpha and beta are `1 + confirmations` and `1 + rejections`, counted by a `GROUP BY`
over `verdict` on every scoring call. The alternative — maintaining alpha/beta in a
state table — is one write cheaper and considerably worse: it can drift from the labels
that produced it, and there is no way to check that it hasn't.

Counting means **deleting a verdict puts the prior back exactly where it was**, which
makes a wrong label a fully reversible mistake rather than a permanent nudge.
`test_the_prior_is_derived_from_rows_not_kept_as_state` is the guard.

### D2. The prior goes through `Store.q`, and this was a real hole

`prior()` used a bare `con.execute`. P is the fifth score component and it renders on
every hypothesis card — so it was **the one number on screen with no `query_id`**, in a
product whose entire claim is that every number traces to a query.

This was not a third exception to that rule (the two — telemetry and redactions — are
facts about the *process*, and both say so on screen). It was an oversight, and routing
it through `q()` closes it. `Hypothesis.query_ids` now carries the prior's query, so it
reaches `card_query_ids` and the provenance audit like anything else.

The empty-string case is preserved: `prior(None, ...)` returns `(0.5, "")` for pure
scoring paths with no database, and `hypothesis.score` filters falsy ids rather than
making every consumer know that the prior is the one component computable without a
query.

### D3. `record()` must invalidate, or the loop only looks closed

`Store.q` memoises on `query_id` and never expires — correct, because the fact table is
immutable within a run. **`verdict` is the single exception**: the UI writes to it.

Without invalidation the failure is quiet and total: the row lands, the prior moves in
the database, and the next diagnosis reads the memoised count from before it. The reader
sees an unchanged P and concludes the feature does nothing.

`Store.invalidate(label)` drops only the entries logged under that label. A blunt
`_q_cache.clear()` would also work and would make every subsequent diagnosis report cold
execution counts — quietly corrupting the telemetry panel, which exists to report
exactly that. Both behaviours have tests.

### D4. Feedback is offered to every persona

A verdict is **not a lever**. `decision_rights` gates what a reader may *do* about a
cause; answering *"did this turn out to be right?"* is a different act, and the CFO who
watched the forecast recover is as well placed to answer as the analyst. Conflating the
two would silence the people best positioned to close the loop.

**Known gap, documented not fixed:** there is no authentication in this build, so the
`verdict` row records *what* was decided and not *who* decided it. Adding a role column
is trivial; making it mean anything requires identity the prototype does not have.
Naming the gap is the honest option — see `roles_decisions.md` D7 for the same posture.

### D5. `feedback_key` is a cache buster, not an input

`app.load_payload`'s cache key gains `feedback_key`, and **`diagnose()` never reads it**.
Its only job is to change when a verdict is recorded, so the memoised payload is
discarded and the scores are recomputed against the new prior. The docstring says so
outright, because a parameter nothing reads is exactly the kind of thing a later reader
deletes as dead.

### D6. The suite must start from an uninformed prior

`data/ledgerlens.duckdb` persists between runs and `verdict` is the one table the app
writes to. A verdict left behind by a UI test — or by a human clicking 👍 during a demo —
shifts P from 0.5 to 0.667, moving the acceptance test's `0.700` by 0.008 against its
`0.01` tolerance. **A flake that only fires on the next run.**

Two guards: the session `store` fixture truncates `verdict` at setup, so the suite is
hermetic even after a crash or a manual click; and the `clean_verdicts` fixture restores
the uninformed prior after any test that deliberately records one.

## 3. Things not to do to this code

- **Do not cache alpha/beta.** See D1 — the reversibility is the feature.
- **Do not read the prior with `con.execute`.** See D2; it is a scored number on screen.
- **Do not remove the `invalidate` call in `record()`.** See D3; the loop silently opens.
- **Do not raise P's weight to make feedback feel more responsive.** At 0.05 it cannot
  overturn a control. That bound is what makes the loop safe to expose to users at all.
