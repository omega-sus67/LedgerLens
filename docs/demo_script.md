# Demo Video — Shot Script

**Target: 3:00.** Nine beats. Every number below is what the app actually prints at
`mrr_renewals`, as-of `2026-08-17` — verify against the screen before recording; if the
app disagrees with this script, **the script is wrong**, not the app.

> **This replaces the beat list in `taskflow/taskflow.md` §12.5**, which predates the AI
> lane and closes on *"$0.0000 per diagnosis"* — a line that was true before the
> investigator existed and is now only true with the lane switched off.

---

## Before you hit record

```bash
export GEMINI_API_KEY=...                       # or the AI beats cannot be filmed
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m streamlit run app.py
```

1. **Warm the cache.** Load the page once and let the first diagnosis finish. Cold is
   ~1.3 s, warm ~0.5 s — you want the snappy one on camera.
2. **Reset the sidebar**: metric `mrr_renewals`, as-of `2026-08-17`, persona
   `Revenue Analyst`, both toggles **off**.
3. **Clear stray verdicts** so the prior starts uninformed and beat 8 reads `0 confirmed`:
   ```bash
   .venv/bin/python -c "from ledgerlens.store import Store; s=Store(); s.con.execute('DELETE FROM verdict'); s.close()"
   ```
4. Browser at ~90% zoom, window ~1600×1000. Hide bookmarks.

---

## Beat 1 — The pain (0:00–0:20)

**Show:** the headline card, before scrolling.

> "A dashboard tells you renewals fell 8%. It cannot tell you why. That question costs an
> analyst three days across Slack, deploy logs and support tickets — and the expensive
> part isn't the delay. It's acting on the wrong why."

## Beat 2 — The anomaly, decomposed (0:20–0:40)

**Show:** the metric row and the diagnosis summary.

> "LedgerLens says renewals are **8.3% below baseline**. Of that, **0.9% is ordinary August
> seasonality** — the system separates the calendar from the incident, so the number it
> asks you to care about is the remaining **7.5%**."

## Beat 3 — Drill-down (0:40–0:55)

**Show:** the attribution table; point at the `◀ focal` row.

> "It narrows the damage to its smallest carrying slice: **DACH, Enterprise, SEPA**. That
> slice is down **85%** — a **$416,144** shortfall — and accounts for **95%** of the parent
> drop. Three of ninety-nine slices explain almost the whole thing."

## Beat 4 — The decoy dies ★ (0:55–1:30)

**The most persuasive thirty seconds in the product. Do not rush it.**

**Show:** scroll to the **REJECTED** card. Expand its control table.

> "Here's the one that matters. Marketing cut spend in DACH **one day before** renewals
> broke. It is temporally *more* plausible than the truth, and a correlation-ranker puts
> it first."
>
> "The engine tries to kill it instead. A demand-side cut to a region has no mechanism
> that spares Mid-market and SMB customers in that region — so it predicts they should
> have dropped too. **They came in flat at −1.3%.**"
>
> "That control failure is decisive. The decoy isn't outranked at **0.322** — it's
> **rejected**. Being second isn't good enough; a decoy still on the list is one an
> executive might act on."

**Then show the winner:** `deploy_sepa_v214`, **0.700**, survived **all 4** of its controls.

## Beat 5 — The AI investigator ★ (1:30–2:00)

**Show:** tick **Run the AI investigator** in the sidebar. Scroll to 🤖 *The investigator lane*.

> "Now the AI. The model reads the anomaly, the candidates and the controls already run,
> and proposes further checks — but only by filling a **fixed vocabulary**. It doesn't
> write SQL. **We** execute the checks."

**Point at the accepted/rejected line** — read the real numbers off screen:

> "Note the denominator: **N accepted, M rejected by validation**. Rejected ones named a
> region or a metric that doesn't exist. They never became a query."

**Point at the failing ticket check:**

> "And this one *failed* — support tickets in that cohort spiked. A failed 'should be
> flat' is evidence the cohort **was** hit."

**Scroll to the unverifiable-causes panel:**

> "And the honest part: causes the connected data **cannot** test, each naming the feed
> that would settle it."

## Beat 6 — The guard ★ (2:00–2:15)

**Show:** the green banner under the panels, then scroll up to the rewritten headline.

> "The headline was written by the model — and it passed the **numbers guard**: every
> figure in it appears in the verified payload. One invented digit and the whole
> narration is thrown away for the deterministic template. **The AI writes the prose. It
> never writes the numbers.**"

## Beat 7 — Four audiences, one computation (2:15–2:35)

**Show:** flip persona `Revenue Analyst → CFO → Payments On-Call`.

> "Same evidence, four readers. The CFO gets dollars and forecast risk — and an
> *escalation*, never an instruction to roll back a release, because she doesn't hold that
> lever. On-call gets the event id and the rollback."
>
> "These aren't four analyses. It's **one computation**, rendered four ways — the query
> ids underneath are identical."

## Beat 8 — It learns, and it refuses (2:35–2:50)

**Show:** click 👍 **Correct** on the top hypothesis; point at P moving off `0.50`.

> "An analyst confirms it. **P** is a posterior counted from verdicts — no model state,
> and deleting the row puts it back exactly where it was. It's weighted 0.05, so it
> sharpens a ranking and can never overturn a control."

**Then tick "Deploy source (github) not connected":**

> "And when the evidence isn't there — it says so. Drop the deploy feed and it **refuses
> to name a cause**, tells you which sources are missing, and stops. It degrades toward
> *I don't know*, not toward a confident wrong answer."

## Beat 9 — Close on the telemetry (2:50–3:00)

**Show:** expand ⏱ **Telemetry**.

> "Every number on this page came from a logged SQL query you can re-run — **22** of them
> on this card. The ranking path never calls a model. The AI cost **half a cent**."
>
> "Dashboards tell you what moved. This tells you why — and shows its work."

---

## If something goes wrong on camera

| Symptom | Cause | Fix |
|---|---|---|
| AI panels absent | `GEMINI_API_KEY` unset | Sidebar caption names the variable; export and restart |
| "the model's prose was discarded" (red) | Guard fired — the model invented a number | **This is a legitimate take.** It demonstrates the guard. Narrate it. |
| Prior already above `0.50` | Leftover verdicts | Run the `DELETE FROM verdict` above |
| Fixture errors / DB lock | Another process holds DuckDB | Close other Streamlit or pytest runs — the lock is exclusive |
| Numbers differ from this script | Data regenerated with a changed seed | `.venv/bin/python -m ledgerlens.gen_data`, then re-verify |
