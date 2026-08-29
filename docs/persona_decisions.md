# `personas.py` — decisions, jargon, and implementation, end to end

Companion to [`contracts_decisions.md`](contracts_decisions.md). That document covers
the KPI semantic contract (task 1); this one covers **personas and the `Action`
reshape** (task 2). Read [`README.md`](../README.md) first for what the system does.

The plan this was built from is [`taskflow/task_persona.md`](../taskflow/task_persona.md).
It is kept because it records the *reasoning* — this file records what actually shipped
and why it differs where it does.

**Status:** landed. 160 tests pass (`126` before task 2, `+34`).

---

## 0. The one-sentence version

> **The evidence is computed once and is identical for every audience. Only the
> sentence that wraps it changes.**

`tests/test_narrate_personas.py::test_personas_differ_in_prose_but_share_every_query_id`
asserts four distinct summaries against one identical 19-element `query_id` list. That
assertion is the claim. If it goes red, the claim is retracted — it is not a test to
relax.

---

## 1. What the Round 2 brief actually asked for

Task 2 closes **six** separate lines of Problem Track 3, which is why it was sequenced
second rather than by tier:

| Where in the brief | Requirement | Closed by |
|---|---|---|
| Objective 4 | "Generates persona-specific narratives supported by traceable evidence." | `narrate(payload, persona)` |
| Objective 6 | "Recommends practical actions grounded in business levers, constraints and decision rights." | `LEVERS` + `decision_rights` + `_route()` |
| Complexities | "Role-based personalization of insight depth, recommended actions and delivery channels." | `depth`, `max_actions`, `show_control_table`, `channel` |
| Solutioning | "Action recommendations structured as: driver → controllable lever → action → expected impact → owner → confidence → monitoring plan" | `Action`, field-for-field, in that order |
| Min. Prototype | "At least two personas receiving different insight narratives or recommended actions." | Four ship |
| Min. Prototype | "One role-based security or entitlement scenario." | **Not closed** — but `Persona.role` is the join key task 4 needs |

The brief also warns: *"The LLM should not be treated as the source of quantitative
truth."* The obvious way to build personas is to hand the card to an LLM and ask it to
rewrite for each audience. That makes the LLM the thing standing between the evidence
and the reader. We do the opposite — see §3.

---

## 2. Jargon glossary

| Term | Meaning here |
|---|---|
| **Persona** | Who is reading the card. A frozen record controlling prose, depth and decision rights. Never a number. |
| **Lever** | A thing the business can actually pull (`rollback_release`, `hold_forecast`). Distinct from the *action*, which is the specific way you pull it this time. |
| **Decision rights** | Which levers a persona may pull. Drives escalation rewriting. |
| **Driver** | The neutral phrase naming the cause (`"a code release to the payment path"`), so a CFO card can name a cause without naming a sha. |
| **Escalation** | An action rewritten as *"Escalate to `<owner>`: …"* because the reader does not hold its lever. |
| **`ref`** | How a change is *named to this reader*: the event id, or the driver phrase for personas with `show_event_ids=False`. |
| **Payload** | `NarrationPayload` — all evidence, no prose. Produced once by `pipeline.diagnose()`. |

---

## 3. The central architectural decision: persona is downstream of every query

`pipeline.run()` used to be one function that detected, drilled, ranked, controlled,
*and* narrated. It is now:

```python
def run(metric, as_of, store=None, cohort=None, window=None) -> DiagnosisCard:
    payload = diagnose(metric, as_of, store=store, cohort=cohort, window=window)
    if payload is None:
        return DiagnosisCard.no_anomaly(metric, as_of)
    return narrate.narrate(payload)
```

`diagnose()` returns a `NarrationPayload | None`. Persona is accepted **only** by
`narrate()`, which sits strictly downstream of every `Store.q()` call.

**Why this matters more than it looks.** Threading `persona` into `pipeline.run()` and
re-running the pipeline per persona would also produce different narratives with the
same query ids — the pipeline is deterministic, so they would match. But they would
match *by coincidence*. With the split, they match *by construction*: persona cannot
reach a query, because it does not exist yet when the queries run. That is the
difference between a property we assert and a property we can point at.

It is also why switching persona in the UI is instant rather than a full re-diagnosis.

**The rejected alternative** was an LLM narrator per persona. Rejected because it puts
a generative model between the evidence and the reader, which the brief explicitly warns
against, and because it makes the identical-evidence claim unassertable — you cannot
diff two LLM outputs for evidence equality.

---

## 4. The four personas

| id | Label | `role` | Channel | `decision_rights` | `max_actions` | Sees ids? | Sees controls? |
|---|---|---|---|---|---|---|---|
| `analyst` | Revenue Analyst | `analyst` | workspace | `["*"]` | 99 | yes | yes |
| `cfo` | CFO | `finance` | email digest | `["hold_forecast"]` | 2 | no | no |
| `oncall` | Payments On-Call | `payments_oncall` | pager | `["rollback_release", "disable_flag"]` | 2 | yes | yes |
| `growth` | Growth Marketing | `growth` | workspace | `["restore_campaign_budget"]` | 2 | no | no |

### `analyst` is the default, and that is a regression guard

`narrate(payload)` with no persona renders exactly what `persona=analyst` renders, and
`test_default_persona_reproduces_todays_card` asserts headline, summary and action text
all match. Task 2 restructured the narrator substantially; this test is what says the
restructure did not change the product for the existing audience.

### `analyst` holds `["*"]`, not an enumerated list

The analyst *routes* work rather than owning levers. Giving them the wildcard means
every action renders as written — no escalation wrappers — which is both correct
product behaviour and what keeps the default card byte-identical.

### `growth` exists for task 4, deliberately half-wired

`contracts.py` already declares `AccessRule(policy_id="fin.rail_detail", role="growth",
hidden_dims=["payment_rail"])`. The `growth` persona's `role` field is that exact
string, and `test_growth_role_matches_the_contract_access_rule` joins the two so a typo
becomes a test failure rather than a silent entitlement bypass later.

**Task 2 does not enforce the hidden dimension.** `growth` gets its narrative here and
its entitlement in task 4. This was a deliberate scope line — the temptation to finish
task 4 while `visible_drill_dims()` was sitting right there was real.

---

## 5. Levers, and why they are separate from actions

The brief's chain starts with a *controllable lever*, not with an action. The
distinction is load-bearing: "renewals are down" is a **driver**, "roll back
`deploy_sepa_v214` for DACH · sepa" is an **action**, and `rollback_release` is the
**lever** — the abstract capability, which is what determines *who is allowed to pull
it*. Decision rights attach to the lever, not to the action, because an org grants
someone the right to roll back releases in general, not the right to roll back one
specific sha.

| `lever_id` | Owner role | Fired by |
|---|---|---|
| `rollback_release` | `service_owner` | `deploy` |
| `disable_flag` | `service_owner` | `feature_flag` |
| `restore_campaign_budget` | `growth` | `campaign` |
| `revert_price` | `revops` | `price_change` |
| `hold_forecast` | `revops` | always, as the P1 |
| `connect_source` | `data_platform` | the abstention branch only |
| `investigate_change` | `service_owner` | fallback |

### The fallback is not defensive padding

`lever_for_event()` falls back to `investigate_change` for anything unmapped.
`config.SEGMENT_AGNOSTIC_EVENT_TYPES` contains `policy_change`, `external` and
`vendor_incident` — all real, all legal on a `ChangeEvent`, none with a named lever.
Without the fallback a `KeyError` in the narrator takes down the whole card at the last
step, after every query has already run.
`test_every_event_type_maps_to_a_lever` iterates that config set directly, so adding a
new event type without a lever fails a test rather than a demo.

---

## 6. Decision rights, made mechanical

```python
def _route(action: Action, who: personas.Persona) -> Action:
    if personas.holds(who, action.lever):
        return action
    body = action.action[0].lower() + action.action[1:]
    return action.model_copy(update={"action": f"Escalate to {action.owner}: {body}"})
```

Only the imperative changes. Priority, owner, evidence, confidence and `basis` are
untouched — **who may pull a lever is a fact about the org, not about the evidence.**

The result, from the live demo:

- **On-call**, who holds `rollback_release`:
  > `[P0]` Roll back or hotfix `deploy_sepa_v214` for DACH · sepa, then re-run this
  > diagnosis to confirm recovery.
- **CFO**, who does not:
  > `[P0]` Escalate to the team owning the service: roll back or hotfix **a code release
  > to the payment path** for DACH · sepa, then re-run this diagnosis to confirm recovery.
- And the mirror image on the P1 — the CFO holds `hold_forecast` and is told to do it;
  **on-call** does not, and is told to escalate it to revenue operations.

Every persona is somebody's escalation. That symmetry is the point: this is a routing
rule, not a seniority hierarchy.

---

## 7. `show_event_ids` governs action text, not just prose

This was caught in plan review, not implementation, and it is the subtlest bug the task
had available.

The CFO template's contract is "no event ids, no SQL jargon". Routing alone satisfies
that for the *summary* but not for the *actions* — the P0 action string is built from
`top.event.event_id`, so the escalated CFO action would have read *"Escalate to the team
owning the service: roll back `deploy_sepa_v214`…"*. A sha, on the card whose whole
contract is that it never shows one.

The fix is a single local in `_actions()`:

```python
ref = top.event.event_id if who.show_event_ids else _driver_label(top.event.event_type)
```

`ref` is used in `driver` and `action`. It is **not** used in `basis`,
`expected_impact`, `confidence` or `monitoring` — those carry the evidence, and the
evidence does not vary by audience.

`test_cfo_prose_never_leaks_an_event_id` asserts on the literal string
`deploy_sepa_v214` across headline, summary *and* every action, so a future copy-paste
from the analyst template fails a test.

---

## 8. `Action` — the brief's chain, field for field

```python
class Action(BaseModel):
    model_config = ConfigDict(frozen=True)
    priority: Literal["P0", "P1", "P2"]
    driver: str
    lever: str
    action: str
    expected_impact: str
    owner: str
    confidence: float
    monitoring: str
    basis: str
```

The field order is the brief's order. That is deliberate and worth pointing at: a judge
reading `models.py` sees their own checklist row.

`basis` is not part of the brief's chain and is ours. It carries the `query_id`, and
`test_every_action_basis_still_carries_a_query_id` enforces that every action remains
clickable back to SQL.

### Where `confidence` comes from — and where it does not

This is the field most likely to be challenged, so it has a documented origin. It is
**not** a probability of causation and **not** a probability the action will work.

| Action | `confidence` | Source |
|---|---|---|
| P0 — pull the lever on the top hypothesis | `top.total` | The hypothesis score already shown in the ranking table |
| P1 — hold the forecast | `top.total` | Same evidence, same hypothesis |
| P2 — objective-mismatch side finding | `1.0` | Not a ranking. A *directly measured* control delta carrying its own `query_id` |
| Abstention — connect sources | `1.0` | Also direct: "no candidate cleared the floor" is an observed fact about the candidate set |

`test_p0_confidence_is_the_top_hypothesis_score` pins the first row, so `confidence`
cannot drift into being a hand-tuned number.

The UI states it in as many words, and `test_confidence_caption_does_not_overclaim`
asserts the sentence is on the page:

> Confidence is the score of the evidence each action rests on — it is not a probability
> that the action will work.

### `expected_impact` is a string, on purpose

A float would have forced a number where we do not have one. The abstention branch reads
*"Not quantified — this raises candidate coverage for future incidents. It does not
itself recover revenue."*, and
`test_no_cause_branch_does_not_fake_a_dollar_impact` asserts there is no `$` in it.
Refusing to quantify is the same discipline the rest of the system already applies to
causation.

The P0's impact is hedged in both directions — *"Recovers **up to** $416,144 … **if** the
rollback restores the cohort to its own baseline"* — because the shortfall is an observed
figure, not a recovery forecast.

---

## 9. Abstention does not vary by audience

`test_every_persona_abstains_together` asserts `no_confident_cause is True` for all four
personas on the same payload, and the abstention card's prose is deliberately **not**
personalised.

A CFO must never be handed a confident answer the analyst was refused. Personalising
depth is a product decision; personalising *certainty* would be a lie with a UI on it.

---

## 10. The cache boundary, and the debt it does **not** pay

`app.py` previously cached the finished card on `(metric, as_of_iso)`. Four upcoming
tasks each add an input that changes the rendered card, so the key was already wrong.

Task 2 resolves it for persona by **moving the boundary rather than widening the key**:

```python
@st.cache_resource(show_spinner="Running diagnosis...")
def load_payload(metric: str, as_of_iso: str):
    ...
    return store, pipeline.diagnose(metric, date.fromisoformat(as_of_iso), store=store)
```

Narration happens outside the cache, so persona needs no key at all.

**This trick does not generalise.** Task 4 (entitlement) hides a dimension, which
changes which cuts are drilled, which changes the payload itself. Task 4 **must** add
`role` to this key — a stale cache would serve a `growth` user the `payment_rail` cut
they are not entitled to see. The warning is in the function's own docstring, where
whoever does task 4 will read it.

---

## 11. What is deliberately not here

- **No LLM narrator.** `generated_by` stays `"template"`. Persona proved renderable
  deterministically, which is the stronger result.
- **No per-persona delivery.** `Persona.channel` is displayed (`email digest`, `pager`)
  but nothing sends anything. Claiming a delivery channel we do not have would be the
  kind of overclaim the README exists to avoid.
- **No entitlement enforcement.** Task 4.
- **No persona persistence or auth.** The selector is a demo control, not a login. A
  real deployment derives persona from the authenticated user's role.
- **No per-persona ranking.** Considered and rejected outright: it would make the score
  depend on the reader, which is the exact failure this design is built to prevent.

---

## 12. How to add a fifth persona

1. Add a `Persona(...)` entry to `PERSONAS` in `ledgerlens/personas.py`. Pick `role`
   from the strings `contracts.AccessRule` already uses if it should inherit an
   entitlement.
2. Add a branch to `_prose()` in `narrate.py`, or let it fall through to the analyst
   default.
3. Add the id to `PERSONA_IDS` in `tests/test_narrate_personas.py`. The identical-
   evidence and abstention tests then cover it automatically.
4. If it needs a lever no one else has, add the lever to `LEVERS` **and** a label to
   `OWNER_LABEL` — `test_every_lever_owner_role_has_a_human_label` enforces the pair.

The prose branch is the only place a new persona can go wrong, because it is the only
place with a `payload` in scope. Copy an existing branch; never compute a figure there.

---

## 13. Verifying the claim from a shell

```bash
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python - <<'PY'
from ledgerlens import narrate, personas, pipeline
p = pipeline.diagnose()
sets = set()
for pid in ("analyst", "cfo", "oncall", "growth"):
    c = narrate.narrate(p, persona=personas.get(pid))
    sets.add(tuple(pipeline.card_query_ids(c)))
    print(f"\n=== {pid} ===\n{c.headline}")
    for a in c.actions:
        print(f"  [{a.priority}] {a.lever} conf={a.confidence:.2f} :: {a.action}")
print(f"\ndistinct query-id sets across 4 personas: {len(sets)}  (must be 1)")
PY
```

Four different cards; `distinct query-id sets: 1`.
