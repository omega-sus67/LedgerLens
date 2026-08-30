# Task 2 — Personas + `Action` Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four personas read the *same* diagnosis and get different prose, different action depth, and different decision rights — while `pipeline.card_query_ids()` returns a byte-identical list for all of them.

**Architecture:** Persona is a **rendering concern only**. `pipeline.diagnose()` produces a `NarrationPayload` once; `narrate.narrate(payload, persona)` renders it N ways. Nothing persona-dependent touches the store, the ranker, or the controls — which is what makes "different narratives, same evidence" a structural property rather than a coincidence we assert in prose. `Action` is reshaped to the brief's seven-link chain, and each action is bound to a **controllable lever**; a persona that does not hold decision rights over that lever sees the action as an *escalation* rather than an instruction.

**Tech Stack:** Python 3.12, pydantic v2 (frozen models), Streamlit (`<1.63`), DuckDB, pytest. No LLM anywhere on this path — narration is template-based by design.

**Spec:**
- `taskflow/taskflow.md` § "Task 2 — Personas + `Action` schema" (subtasks 2.1–2.3)
- `details/6a8bd90a9b7ff_accenture_innovation_challenge_round_2_detailed_problem_statements_final_1.pdf`, Problem Track 3 — *BusinessIntelligence.ai*

---

## Global Constraints

- **Test command on this machine:** `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q` — the ROS 2 install poisons `PYTHONPATH` and plain `pytest` dies at collection with `ModuleNotFoundError: No module named 'yaml'`.
- **Baseline: 126 tests pass** (verified Aug 29). Any task that leaves the suite below 126 passing is not done.
- **Every figure on a card must carry a `query_id`.** `Action.basis` is the traceability hook and must never be dropped or left without one.
- **No LLM on the narration path.** `generated_by` stays `"template"`.
- **Pydantic models are frozen** (`ConfigDict(frozen=True)`). Mutate with `.model_copy(update={...})`, never by assignment.
- **Persona must never change a number.** If a task makes a persona affect `ranked`, `controls`, `nodes`, or any `query_id`, that task is wrong.
- **The `@st.cache_resource` key debt is paid in this task.** `CLAUDE.md` flags that `app.py`'s `load()` keys on `(metric, as_of_iso)` only, and that tasks 2, 4, 5 and 7 each add an input affecting the rendered card. Task E resolves it for persona by moving the cache boundary *below* narration rather than by widening the key — see Task E Step 3. **Tasks 4, 5 and 7 cannot reuse that trick**: entitlement changes which dimensions are drilled, so it changes the payload itself. Task 4 must add `role` to `load_payload`'s key. Leave a comment saying so.

---

## Part 1 — What personas are *for*

### 1.1 The brief asks for this in six separate places

Task 2 is the highest-leverage item in the backlog because one change closes six distinct lines of the Round 2 brief. Quoted verbatim from Problem Track 3:

| Where in the PDF | Exact requirement | How this task closes it |
|---|---|---|
| Round 2 Objective **4** | "Generates persona-specific narratives supported by traceable evidence." | Four personas, one payload, identical `card_query_ids()`. Task D. |
| Round 2 Objective **6** | "Recommends practical actions grounded in business levers, constraints and decision rights." | `LEVERS` registry + `Persona.decision_rights` + escalation routing. Tasks A, B, D. |
| Real-World Complexities | "Role-based personalization of insight depth, recommended actions and delivery channels." | `Persona.depth`, `Persona.max_actions`, `Persona.channel`. Tasks A, D. |
| Solutioning Areas | "Action recommendations structured as: driver → controllable lever → action → expected impact → owner → confidence → monitoring plan" | `Action` reshaped to exactly those seven fields, **in that order**. Task B. |
| Minimum Prototype Expectations | "At least two personas receiving different insight narratives or recommended actions." | We ship four. Task D. |
| Minimum Prototype Expectations | "One role-based security or entitlement scenario." | **Not closed here** — but `Persona.role` is the key `contracts.AccessRule.role` already expects, so Task 4 becomes a two-line wiring job instead of a design problem. Task A. |

### 1.2 Why a persona layer is the right answer, not a cosmetic one

The Round 1 pitch was *"root-cause analysis as a set intersection, verified by negative controls."* The obvious objection a judge raises is: **an analyst-shaped card is useless to a CFO, and a CFO-shaped card is useless to on-call.** Most teams answer that by asking an LLM to rewrite the card per audience — which quietly makes the LLM the source of quantitative truth, exactly what the brief warns against:

> "The LLM should not be treated as the source of quantitative truth."

Our answer is structurally different and is the thing to say on stage:

> **The evidence is computed once and is identical for every audience. Only the sentence that wraps it changes. Here is the assertion that proves it, and it runs in CI.**

That claim is worth building the layer for. It is also the cheapest possible way to demonstrate "insight depth personalization" without a second pipeline.

### 1.3 What a persona actually controls

A persona is a small frozen record. It controls exactly five things, and **nothing else**:

1. **Prose register** — which template renders the headline and summary.
2. **Vocabulary gate** — `show_event_ids`. A CFO card must not say `deploy_sepa_v214`; an on-call card must lead with it. This governs **action text as well as prose** — an escalation that names a sha is still a card with a sha on it.
3. **Depth** — `show_control_table`, `max_actions`. On-call wants all four negative controls; the CFO wants a short list and a monitoring plan.
4. **Decision rights** — `decision_rights: list[str]` of lever ids. This is the brief's "decision rights" made mechanical: if you do not hold the lever, the recommendation is rendered as *"Escalate to <owner>: …"* instead of an instruction. A CFO cannot roll back a release, so the CFO is never told to.
5. **Role** — the string that keys `contracts.AccessRule.role`. Unused in this task; it is the hook Task 4 pulls.

Everything else — the ranking, the scores, the controls, the query ids, the numbers — is persona-blind by construction.

### 1.4 The four personas

| id | Label | `role` | Channel | Reads it to… | `decision_rights` |
|---|---|---|---|---|---|
| `analyst` | Revenue Analyst | `analyst` | workspace | route the work and audit every claim | `["*"]` (sees every action as written) |
| `cfo` | CFO | `finance` | email digest | decide what to tell the board about the quarter | `["hold_forecast"]` |
| `oncall` | Payments On-Call | `payments_oncall` | pager | stop the bleeding in the next twenty minutes | `["rollback_release", "disable_flag"]` |
| `growth` | Growth Marketing | `growth` | workspace | find out whether the budget cut is the problem | `["restore_campaign_budget"]` |

`analyst` is the **default** and its card must be byte-identical to today's — that is the regression guard on the whole refactor.

`growth` exists because `ledgerlens/contracts.py:263` already declares an `AccessRule(policy_id="fin.rail_detail", role="growth", hidden_dims=["payment_rail"])`. Adding the persona now costs one dict entry and means Task 4 has a UI surface waiting for it. **Task 2 does not enforce the hidden dimension** — the `growth` persona gets its narrative here and its entitlement in Task 4. Do not half-implement Task 4 inside this one.

### 1.5 Levers and decision rights

The brief's chain starts with a **controllable lever**, not with an action. That distinction matters: "renewals are down" is a driver, "roll back the release" is an action, and the lever is the *thing the business can actually pull* — which is what determines who is allowed to pull it.

We model six levers. Each maps to an owner role, and each event type maps to a lever:

| `lever_id` | Lever | Owner role | Fired by |
|---|---|---|---|
| `rollback_release` | Roll back or hotfix a release | `service_owner` | `deploy` |
| `disable_flag` | Disable a feature flag | `service_owner` | `feature_flag` |
| `restore_campaign_budget` | Restore or re-target campaign budget | `growth` | `campaign` |
| `revert_price` | Revert or grandfather a price change | `revops` | `price_change` |
| `hold_forecast` | Hold the forecast, reclassify as at-risk | `revops` | *(always, as the P1)* |
| `connect_source` | Connect a missing source system | `data_platform` | *(no-cause branch only)* |

Any event type without a mapping falls back to `investigate_change` (owner `service_owner`). That fallback exists so `policy_change`, `external`, and `vendor_incident` — all real values in `SEGMENT_AGNOSTIC_EVENT_TYPES` — never crash the narrator.

### 1.6 Where `confidence` comes from — and where it does not

`confidence: float` is the field most likely to be challenged by a judge, so it must have a defensible origin. It is **not** a probability of causation, and the card says so.

| Action | `confidence` | Source |
|---|---|---|
| P0 — pull the lever on the top hypothesis | `top.total` | The hypothesis score. Already a bounded, weighted, auditable 0–1 number. |
| P1 — hold the forecast | `top.total` | Same evidence, same hypothesis. |
| P2 — objective-mismatch side finding | `1.0` | Not a ranking. This rests on a *directly measured* control delta that carries its own `query_id`. Confidence is in the measurement, not in a causal claim. |
| No-cause branch — connect sources | `1.0` | Also a direct measurement: "no candidate cleared the floor" is an observed fact about the candidate set. |

State this in the UI caption verbatim: *"Confidence is the score of the evidence the action rests on, not a probability that the action will work."*

---

## Part 2 — File structure

| File | Status | Responsibility |
|---|---|---|
| `ledgerlens/personas.py` | **Create** | `Persona`, `Lever`, the `PERSONAS` / `LEVERS` registries, `get()`, `lever_for_event()`, `route()`. Pure data + lookups. No imports from `narrate`, `pipeline`, or `store` — this file must stay a leaf. |
| `ledgerlens/models.py:269` | Modify | Reshape `Action` to the brief's seven-link chain. |
| `ledgerlens/narrate.py` | Modify | `NarrationPayload` gains `no_confident_cause`. `narrate()` gains `persona`. `_cause_card` splits into a shared evidence builder plus per-persona prose. Four `Action` sites updated. |
| `ledgerlens/pipeline.py:31` | Modify | Split `run()` into `diagnose()` (payload) + `run()` (payload → narrate). `run()`'s public signature is unchanged. |
| `app.py` | Modify | Persona selectbox; `load()` caches the *payload*, not the card; render the new `Action` fields. |
| `tests/test_personas.py` | **Create** | Persona registry, lever mapping, decision-rights routing. |
| `tests/test_narrate_personas.py` | **Create** | The headline assertion: different prose, identical query ids. |
| `tests/test_pipeline.py` | Modify | `diagnose()` / `run()` equivalence. |
| `tests/test_app.py:45` | Modify | Action count changes with persona; new fields render. |
| `README.md` | Modify | Persona section + the six-row brief mapping from §1.1. |

Six tasks. Each ends with a green suite and a commit.

---

## Task A: The persona and lever registries

**Files:**
- Create: `ledgerlens/personas.py`
- Test: `tests/test_personas.py`

**Interfaces:**
- Consumes: `config` only.
- Produces:
  - `class Lever(BaseModel)` — `lever_id: str`, `name: str`, `owner_role: str`
  - `class Persona(BaseModel)` — `persona_id: str`, `label: str`, `role: str`, `channel: str`, `depth: Literal["full","summary","operational"]`, `show_event_ids: bool`, `show_control_table: bool`, `max_actions: int`, `decision_rights: list[str]`
  - `LEVERS: dict[str, Lever]`, `PERSONAS: dict[str, Persona]`, `DEFAULT_PERSONA_ID = "analyst"`
  - `get(persona_id: str) -> Persona`
  - `lever_for_event(event_type: str) -> Lever`
  - `holds(persona: Persona, lever_id: str) -> bool`
  - `OWNER_LABEL: dict[str, str]` — owner-role id → human label

- [ ] **Step 1: Write the failing test**

```python
# tests/test_personas.py
"""Persona + lever registries. Pure data, so these are fast and exhaustive."""

from __future__ import annotations

import pytest

import config
from ledgerlens import personas


def test_four_personas_exist_and_analyst_is_default():
    assert set(personas.PERSONAS) == {"analyst", "cfo", "oncall", "growth"}
    assert personas.DEFAULT_PERSONA_ID == "analyst"


def test_analyst_holds_every_lever_via_wildcard():
    """The analyst routes work rather than owning levers, so every action renders
    as written. This is what keeps today's card byte-identical."""
    analyst = personas.get("analyst")
    assert analyst.decision_rights == ["*"]
    for lever_id in personas.LEVERS:
        assert personas.holds(analyst, lever_id)


def test_cfo_cannot_roll_back_a_release():
    """The decision-rights claim, at its sharpest: a CFO is never told to deploy."""
    cfo = personas.get("cfo")
    assert not personas.holds(cfo, "rollback_release")
    assert personas.holds(cfo, "hold_forecast")


def test_oncall_holds_the_operational_levers_only():
    oncall = personas.get("oncall")
    assert personas.holds(oncall, "rollback_release")
    assert personas.holds(oncall, "disable_flag")
    assert not personas.holds(oncall, "hold_forecast")


def test_growth_role_matches_the_contract_access_rule():
    """contracts.py:263 declares AccessRule(role="growth"). Task 4 joins on this
    string, so a typo here is a silent entitlement bypass later."""
    from ledgerlens import contracts

    roles = {r.role for c in contracts.CONTRACTS.values() for r in c.access}
    assert personas.get("growth").role in roles


def test_every_event_type_maps_to_a_lever():
    """No event type may crash the narrator. SEGMENT_AGNOSTIC_EVENT_TYPES contains
    policy_change / external / vendor_incident, none of which have a named lever."""
    known = {"deploy", "feature_flag", "campaign", "price_change"}
    for event_type in known | config.SEGMENT_AGNOSTIC_EVENT_TYPES:
        lever = personas.lever_for_event(event_type)
        assert lever.lever_id in personas.LEVERS


def test_unknown_event_type_falls_back_rather_than_raising():
    assert personas.lever_for_event("something_new").lever_id == "investigate_change"


def test_every_lever_owner_role_has_a_human_label():
    for lever in personas.LEVERS.values():
        assert lever.owner_role in personas.OWNER_LABEL


def test_get_rejects_an_unknown_persona():
    with pytest.raises(KeyError):
        personas.get("ceo")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_personas.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ledgerlens.personas'`

- [ ] **Step 3: Write the implementation**

```python
# ledgerlens/personas.py
"""Personas and business levers.

A persona is a RENDERING concern and nothing else. It never reaches the store, the
ranker or the controls -- which is why the same NarrationPayload can be rendered four
ways and still produce a byte-identical card_query_ids() list. That property is the
pitch; `tests/test_narrate_personas.py` is where it is enforced.

`decision_rights` makes the brief's "decision rights" mechanical: a persona that does
not hold a lever is shown an ESCALATION, never an instruction. A CFO is not told to
roll back a release.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class Lever(BaseModel):
    """A thing the business can actually pull. Distinct from the action, which is
    the specific way you pull it this time."""

    model_config = ConfigDict(frozen=True)
    lever_id: str
    name: str
    owner_role: str


OWNER_LABEL: dict[str, str] = {
    "service_owner": "the team owning the service",
    "revops": "revenue operations",
    "growth": "growth marketing",
    "data_platform": "data platform",
}

LEVERS: dict[str, Lever] = {
    lever.lever_id: lever
    for lever in [
        Lever(lever_id="rollback_release", name="Roll back or hotfix a release", owner_role="service_owner"),
        Lever(lever_id="disable_flag", name="Disable a feature flag", owner_role="service_owner"),
        Lever(lever_id="restore_campaign_budget", name="Restore or re-target campaign budget", owner_role="growth"),
        Lever(lever_id="revert_price", name="Revert or grandfather a price change", owner_role="revops"),
        Lever(lever_id="hold_forecast", name="Hold the forecast, reclassify as at-risk", owner_role="revops"),
        Lever(lever_id="connect_source", name="Connect a missing source system", owner_role="data_platform"),
        Lever(lever_id="investigate_change", name="Investigate the change manually", owner_role="service_owner"),
    ]
}

# Event type -> the lever that change is pulled with. Anything unmapped falls back to
# investigate_change: policy_change, external and vendor_incident are real values in
# config.SEGMENT_AGNOSTIC_EVENT_TYPES and must never crash the narrator.
_LEVER_BY_EVENT_TYPE: dict[str, str] = {
    "deploy": "rollback_release",
    "feature_flag": "disable_flag",
    "campaign": "restore_campaign_budget",
    "price_change": "revert_price",
}


def lever_for_event(event_type: str) -> Lever:
    return LEVERS[_LEVER_BY_EVENT_TYPE.get(event_type, "investigate_change")]


class Persona(BaseModel):
    """Who is reading the card. Controls prose, depth and decision rights -- never
    a number."""

    model_config = ConfigDict(frozen=True)

    persona_id: str
    label: str
    role: str  # keys contracts.AccessRule.role -- Task 4 joins on this
    channel: str
    depth: Literal["full", "summary", "operational"]
    show_event_ids: bool
    show_control_table: bool
    max_actions: int
    decision_rights: list[str]  # lever ids, or ["*"] for all


PERSONAS: dict[str, Persona] = {
    p.persona_id: p
    for p in [
        Persona(
            persona_id="analyst",
            label="Revenue Analyst",
            role="analyst",
            channel="workspace",
            depth="full",
            show_event_ids=True,
            show_control_table=True,
            max_actions=99,
            decision_rights=["*"],
        ),
        Persona(
            persona_id="cfo",
            label="CFO",
            role="finance",
            channel="email digest",
            depth="summary",
            show_event_ids=False,
            show_control_table=False,
            max_actions=2,  # the escalated P0 + hold_forecast, which the CFO owns
            decision_rights=["hold_forecast"],
        ),
        Persona(
            persona_id="oncall",
            label="Payments On-Call",
            role="payments_oncall",
            channel="pager",
            depth="operational",
            show_event_ids=True,
            show_control_table=True,
            max_actions=2,
            decision_rights=["rollback_release", "disable_flag"],
        ),
        Persona(
            persona_id="growth",
            label="Growth Marketing",
            role="growth",
            channel="workspace",
            depth="summary",
            show_event_ids=False,
            show_control_table=False,
            max_actions=2,
            decision_rights=["restore_campaign_budget"],
        ),
    ]
}

DEFAULT_PERSONA_ID = "analyst"


def get(persona_id: str) -> Persona:
    if persona_id not in PERSONAS:
        raise KeyError(f"unknown persona {persona_id!r}; known: {sorted(PERSONAS)}")
    return PERSONAS[persona_id]


def holds(persona: Persona, lever_id: str) -> bool:
    return "*" in persona.decision_rights or lever_id in persona.decision_rights
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_personas.py -q`
Expected: PASS, 9 tests

- [ ] **Step 5: Run the full suite**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q`
Expected: `135 passed` (126 + 9). Nothing else imports `personas` yet, so nothing else can break.

- [ ] **Step 6: Commit**

```bash
git add taskflow/task_persona.md ledgerlens/personas.py tests/test_personas.py
git commit -m "feat(personas): persona and business-lever registries"
```

> The `.gitignore` `*.md` problem described in `taskflow/taskflow.md` § "Two things that will bite us" was **already fixed during Task 1** — the blanket rule is gone and only `improvements.md` is ignored. Verified 2026-08-29 with `git check-ignore -v taskflow/task_persona.md`, which prints nothing. No action needed.

---

## Task B: Reshape `Action` to the brief's seven-link chain

**Files:**
- Modify: `ledgerlens/models.py:269-274`
- Modify: `ledgerlens/narrate.py` (four `Action(...)` sites: ~183, ~192, ~209, ~275)
- Test: `tests/test_narrate_actions.py` (create)

**Interfaces:**
- Consumes: `personas.LEVERS`, `personas.lever_for_event`, `personas.OWNER_LABEL` from Task A.
- Produces: the new `Action` shape, consumed by Tasks D and E.

**This task is persona-blind.** Every card still renders exactly as today; only the `Action` payload gets richer. Splitting it out this way means a reviewer can reject the schema without rejecting the persona layer.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_narrate_actions.py
"""The Action schema is a literal row on the judges' list:
'driver -> controllable lever -> action -> expected impact -> owner -> confidence
-> monitoring plan'. These tests assert the chain is complete and grounded."""

from __future__ import annotations

import pytest

import config
from ledgerlens import personas, pipeline


@pytest.fixture(scope="module")
def card(store):
    return pipeline.run("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)


def test_every_action_completes_the_seven_link_chain(card):
    assert card.actions
    for a in card.actions:
        assert a.driver, "driver is the first link and may not be blank"
        assert a.lever in personas.LEVERS, f"{a.lever!r} is not a registered lever"
        assert a.action
        assert a.expected_impact
        assert a.owner
        assert 0.0 <= a.confidence <= 1.0
        assert a.monitoring


def test_every_action_basis_still_carries_a_query_id(card):
    """The traceability hook. An action a judge cannot click back to SQL is a bug."""
    for a in card.actions:
        assert "[" in a.basis and "]" in a.basis


def test_p0_confidence_is_the_top_hypothesis_score(card):
    """Not an invented number: it is the score already shown in the ranking table."""
    p0 = next(a for a in card.actions if a.priority == "P0")
    assert p0.confidence == pytest.approx(card.ranked[0].total)


def test_p0_pulls_the_lever_matching_the_top_event_type(card):
    p0 = next(a for a in card.actions if a.priority == "P0")
    expected = personas.lever_for_event(card.ranked[0].event.event_type)
    assert p0.lever == expected.lever_id


def test_p1_holds_the_forecast(card):
    p1 = next(a for a in card.actions if a.priority == "P1")
    assert p1.lever == "hold_forecast"


def test_monitoring_plan_cites_the_control_band_rather_than_a_magic_number(card):
    p0 = next(a for a in card.actions if a.priority == "P0")
    assert f"{config.CONTROL_PASS_BAND_PCT:.0f}%" in p0.monitoring


def test_no_cause_branch_does_not_fake_a_dollar_impact(store):
    """Abstention must stay honest: we do not quantify the value of connecting a
    source we have never seen."""
    from datetime import date

    from ledgerlens import narrate

    payload = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    card = narrate.narrate(payload.model_copy(update={"no_confident_cause": True}))
    action = card.actions[0]
    assert action.lever == "connect_source"
    assert "$" not in action.expected_impact
    assert "not quantified" in action.expected_impact.lower()
```

> **Note for the executor:** `test_no_cause_branch_does_not_fake_a_dollar_impact` calls `pipeline.diagnose`, which does not exist until **Task C**. Write the test now but mark it `@pytest.mark.xfail(reason="pipeline.diagnose lands in Task C", strict=True)` and delete the mark in Task C Step 5. The `card` fixture uses `pipeline.run`, which already exists, so the other six tests pass in this task.

- [ ] **Step 2: Run the test to verify it fails**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_narrate_actions.py -q`
Expected: FAIL — `AttributeError: 'Action' object has no attribute 'driver'`

- [ ] **Step 3: Reshape the model**

Replace `ledgerlens/models.py:269-274` with:

```python
class Action(BaseModel):
    """The brief's recommendation chain, in the brief's order:

        driver -> controllable lever -> action -> expected impact
               -> owner -> confidence -> monitoring plan

    `basis` is not part of that chain and is ours: it carries the query_id, which is
    what lets a reader click any recommendation back to the SQL underneath it.

    `confidence` is the score of the EVIDENCE the action rests on -- the hypothesis
    score for cause-linked actions, 1.0 for directly measured ones. It is not a
    probability that the action will work, and the UI says so.
    """

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

- [ ] **Step 4: Fill the new fields at all four construction sites**

In `ledgerlens/narrate.py`, add to the imports:

```python
from ledgerlens import personas
```

Add a driver-label map next to `OWNER_BY_SOURCE`:

```python
# A neutral phrase for the driver, so a CFO card can name the cause without naming
# the event id. `show_event_ids` personas append the id themselves.
DRIVER_LABEL_BY_EVENT_TYPE = {
    "deploy": "a code release to the payment path",
    "feature_flag": "a feature flag rollout",
    "campaign": "a marketing budget change",
    "price_change": "a list-price change",
    "policy_change": "a billing policy change",
    "external": "an external market event",
    "vendor_incident": "a payment vendor incident",
}


def _driver_label(event_type: str) -> str:
    return DRIVER_LABEL_BY_EVENT_TYPE.get(event_type, "a recorded change")
```

Then the four sites. **P0** (`narrate.py:183`):

```python
    lever = personas.lever_for_event(top.event.event_type)
    actions = [
        Action(
            priority="P0",
            driver=f"{_driver_label(top.event.event_type)} ({top.event.event_id})",
            lever=lever.lever_id,
            action=(
                f"Roll back or hotfix {top.event.event_id} for {cohort_label(top.event.blast_radius)}, "
                f"then re-run this diagnosis to confirm recovery."
            ),
            expected_impact=(
                f"Recovers up to {_money(abs(focal.delta_abs))} of the {focal.window.days}-day "
                f"shortfall if the rollback restores the cohort to its own baseline."
            ),
            owner=owner,
            confidence=top.total,
            monitoring=(
                f"Re-run this diagnosis daily. {cohort} back within "
                f"{config.CONTROL_PASS_BAND_PCT:.0f}% of baseline within 3 days, or escalate."
            ),
            basis=f"{_money(focal.delta_abs)} shortfall over {focal.window.days} days [{focal.query_id}]",
        ),
```

**P1** (`narrate.py:192`):

```python
        Action(
            priority="P1",
            driver=f"{_driver_label(top.event.event_type)} ({top.event.event_id})",
            lever="hold_forecast",
            action=(
                f"Hold the {cohort_label({k: v for k, v in focal.cohort.items() if k == 'region'})} "
                f"renewals forecast until the rail recovers; treat the shortfall as at-risk, "
                f"not lost."
            ),
            expected_impact=(
                f"Reclassifies {_money(abs(focal.delta_abs))} from lost to at-risk in the "
                f"current forecast. No revenue effect on its own."
            ),
            owner=personas.OWNER_LABEL["revops"],
            confidence=top.total,
            monitoring=(
                f"Release the hold after the cohort sits within "
                f"{config.CONTROL_PASS_BAND_PCT:.0f}% of baseline for 3 consecutive days."
            ),
            basis=f"focal cohort actual {_money(focal.actual)} vs expected {_money(focal.expected)} [{focal.query_id}]",
        ),
    ]
```

**P2** (`narrate.py:209`):

```python
            actions.append(
                Action(
                    priority="P2",
                    driver=f"{_driver_label(rejected.event.event_type)} ({rejected.event.event_id})",
                    lever=personas.lever_for_event(rejected.event.event_type).lever_id,
                    action=(
                        f"Separately: {rejected.event.event_id} did not cause this, but it is "
                        f"doing what it was designed to do to {objective.metric}. Confirm that "
                        f"trade-off is intended."
                    ),
                    expected_impact=(
                        f"Restoring the budget would be expected to recover the "
                        f"{abs(objective.observed_delta_pct):.0f}% drop in {objective.metric}; "
                        f"it would not affect this incident."
                    ),
                    owner=OWNER_BY_SOURCE.get(rejected.event.source, "the change owner"),
                    confidence=1.0,  # a measured control delta, not a ranking
                    monitoring=(
                        f"Track {objective.metric} in {cohort_label(objective.cohort)} weekly "
                        f"against its pre-change baseline."
                    ),
                    basis=f"{objective.metric} {objective.observed_delta_pct:+.1f}% in "
                    f"{cohort_label(objective.cohort)} [{objective.query_id}]",
                )
            )
```

**No-cause** (`narrate.py:275`):

```python
        actions=[
            Action(
                priority="P1",
                driver="no recorded change whose blast radius touches this cohort",
                lever="connect_source",
                action=f"Connect {missing} so the next incident of this shape has candidates to test.",
                expected_impact=(
                    "Not quantified -- this raises candidate coverage for future incidents. "
                    "It does not itself recover revenue."
                ),
                owner=personas.OWNER_LABEL["data_platform"],
                confidence=1.0,  # the absence of a candidate is directly observed
                monitoring="Re-run this diagnosis after each new source lands.",
                basis=f"no candidate above {config.SCORE_FLOOR} [{focal.query_id}]",
            )
        ],
```

- [ ] **Step 5: Run the tests**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q`
Expected: `141 passed, 1 xfailed` (135 + 6 new passing, 1 xfail waiting on Task C).
If `test_app.py` fails on the action rendering, that is expected — fix it in **Task E**, not here; if it blocks, mark it xfail with `reason="Action fields render in Task E"`.

- [ ] **Step 6: Commit**

```bash
git add ledgerlens/models.py ledgerlens/narrate.py tests/test_narrate_actions.py
git commit -m "feat(actions): reshape Action to driver -> lever -> action -> impact -> owner -> confidence -> monitoring"
```

---

## Task C: Split `pipeline.run` into `diagnose` + `run`

**Files:**
- Modify: `ledgerlens/pipeline.py:31-83`
- Modify: `ledgerlens/narrate.py` (`NarrationPayload` gains `no_confident_cause`)
- Test: `tests/test_pipeline.py` (add)

**Interfaces:**
- Produces: `pipeline.diagnose(metric, as_of, store=None, cohort=None, window=None) -> NarrationPayload | None`. Returns `None` when there is no anomaly at all.
- `pipeline.run(...)`'s existing signature and return type are **unchanged** — it gains only an optional `persona: Persona | None = None` in Task D.

**Why this task exists.** Without it, `app.py` would have to re-run the whole pipeline for every persona switch, and "same evidence" would be a coincidence of determinism rather than a structural fact. With it, the payload is computed once and rendered N times, which is both the faster demo and the stronger claim.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline.py  (append)

def test_diagnose_and_run_agree_on_every_query_id(store):
    """run() must be exactly narrate(diagnose()). If these ever diverge, the
    'same evidence, different narrative' claim is dead."""
    from ledgerlens import narrate

    payload = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    assert payload is not None
    from_payload = narrate.narrate(payload)
    from_run = pipeline.run("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)

    assert pipeline.card_query_ids(from_payload) == pipeline.card_query_ids(from_run)
    assert from_payload.summary == from_run.summary
    assert from_payload.headline == from_run.headline


def test_diagnose_returns_none_when_there_is_no_anomaly(store):
    from datetime import date

    assert pipeline.diagnose("mrr_renewals", date(2026, 7, 31), store=store) is None


def test_payload_carries_the_abstention_flag(store):
    payload = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    assert payload.no_confident_cause is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_pipeline.py -q`
Expected: FAIL — `AttributeError: module 'ledgerlens.pipeline' has no attribute 'diagnose'`

- [ ] **Step 3: Add the flag to `NarrationPayload`**

`NarrationPayload` is a plain `@dataclass`, so a defaulted field must go last:

```python
@dataclass
class NarrationPayload:
    metric: str
    root: Anomaly
    focal: Anomaly
    nodes: list[Anomaly]
    ranked: list[Hypothesis]
    rejected: list[Hypothesis]
    symptoms: list[SymptomCluster]
    seasonal_pct: float
    seasonal_query_id: str
    no_confident_cause: bool = False
```

`narrate()` keeps its `no_confident_cause` keyword for backwards compatibility, defaulting to the payload's own flag:

```python
def narrate(payload: NarrationPayload, no_confident_cause: bool | None = None) -> DiagnosisCard:
    abstain = payload.no_confident_cause if no_confident_cause is None else no_confident_cause
    if abstain or not payload.ranked:
        return _no_cause_card(payload)
    return _cause_card(payload)
```

> `NarrationPayload` is a dataclass, not a pydantic model, so `.model_copy()` does **not** exist on it. Task B's `test_no_cause_branch_does_not_fake_a_dollar_impact` must use `dataclasses.replace(payload, no_confident_cause=True)` instead. Fix that test now.

- [ ] **Step 4: Extract `diagnose`**

Replace the body of `pipeline.py:31-83` with:

```python
def diagnose(
    metric: str = "mrr_renewals",
    as_of: date = DEFAULT_AS_OF,
    store: Store | None = None,
    cohort: Cohort | None = None,
    window: Window | None = None,
) -> narrate.NarrationPayload | None:
    """Everything up to, but not including, prose. Returns None when there is no
    anomaly to explain.

    Split out from run() so a card can be rendered for several personas from ONE
    computation. That is what makes 'identical evidence, different narrative' a
    structural property rather than a coincidence of determinism.
    """
    store = store or get_store()

    if cohort is not None and window is not None:
        ev, query_id = anomaly.measure(store, metric, cohort, window)
        if ev is None:
            return None
        root = anomaly._anomaly_from_eval(
            metric, cohort, window, window.start, ev, query_id, 1.0, 0, None
        )
        nodes = [root]
    else:
        root = anomaly.detect(store, metric, as_of)
        if root is None:
            return None
        nodes = anomaly.drill(store, root, config.DRILL_DIMS)

    focal = anomaly.focal(nodes)
    symptoms = symptoms_mod.cluster(store, focal.window)
    hyps = hypothesis.rank(store, focal, symptoms)

    ranked = [h for h in hyps if h.rejection_reason is None]
    rejected = [h for h in hyps if h.rejection_reason is not None]
    seasonal_pct, seasonal_query_id = anomaly.seasonal_estimate(store, metric, root.cohort)

    return narrate.NarrationPayload(
        metric=metric,
        root=root,
        focal=focal,
        nodes=nodes,
        ranked=ranked,
        rejected=rejected,
        symptoms=symptoms,
        seasonal_pct=seasonal_pct,
        seasonal_query_id=seasonal_query_id,
        no_confident_cause=not ranked or ranked[0].total < config.SCORE_FLOOR,
    )


def run(
    metric: str = "mrr_renewals",
    as_of: date = DEFAULT_AS_OF,
    store: Store | None = None,
    cohort: Cohort | None = None,
    window: Window | None = None,
) -> DiagnosisCard:
    """Diagnose `metric` as of `as_of`.

    Passing `cohort`/`window` bypasses detection entirely. Detection is advisory, not
    gating: every blind spot it has (slow drifts, ratio metrics, interaction effects,
    offsetting moves that cancel at the root) becomes "we don't auto-surface this"
    rather than "we can't diagnose this", because the downstream chain does not care
    where the focal anomaly came from.
    """
    payload = diagnose(metric, as_of, store=store, cohort=cohort, window=window)
    if payload is None:
        return DiagnosisCard.no_anomaly(metric, as_of)
    return narrate.narrate(payload)
```

- [ ] **Step 5: Un-xfail Task B's two deferred tests**

Delete the `@pytest.mark.xfail` decorators added in Task B Step 1, and change that test's payload mutation to `dataclasses.replace(payload, no_confident_cause=True)`.

- [ ] **Step 6: Run the full suite**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q`
Expected: `145 passed`, **zero xfailed** (141 + 3 new + the un-xfailed one). This is a pure refactor — if any pre-existing test changed behaviour, the extraction is wrong. Revert and redo rather than editing the assertion.

- [ ] **Step 7: Commit**

```bash
git add ledgerlens/pipeline.py ledgerlens/narrate.py tests/test_pipeline.py tests/test_narrate_actions.py
git commit -m "refactor(pipeline): split diagnose() from run() so one payload renders many cards"
```

---

## Task D: Persona-aware narration

**Files:**
- Modify: `ledgerlens/narrate.py`
- Test: `tests/test_narrate_personas.py` (create)

**Interfaces:**
- Consumes: `personas.Persona`, `personas.holds`, `personas.OWNER_LABEL` (Task A); the new `Action` shape (Task B); `pipeline.diagnose` (Task C).
- Produces: `narrate.narrate(payload, persona: Persona | None = None, no_confident_cause: bool | None = None) -> DiagnosisCard`. `persona=None` means the analyst default.

**This is the task the whole plan exists for.** The load-bearing assertion is `test_personas_differ_in_prose_but_share_every_query_id`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_narrate_personas.py
"""Two audiences, identical evidence.

'Different narratives, same query_ids' is the sentence we say to judges. This file
is that sentence, machine-checked. If it ever goes red, the claim is retracted --
do not weaken the assertion to make it pass.
"""

from __future__ import annotations

import pytest

from ledgerlens import narrate, personas, pipeline

PERSONA_IDS = ["analyst", "cfo", "oncall", "growth"]


@pytest.fixture(scope="module")
def payload(store):
    p = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    assert p is not None
    return p


@pytest.fixture(scope="module")
def cards(payload):
    return {pid: narrate.narrate(payload, persona=personas.get(pid)) for pid in PERSONA_IDS}


def test_personas_differ_in_prose_but_share_every_query_id(cards):
    """THE assertion. Four different summaries; one identical evidence set."""
    summaries = {c.summary for c in cards.values()}
    assert len(summaries) == len(PERSONA_IDS), "two personas produced identical prose"

    id_sets = [pipeline.card_query_ids(c) for c in cards.values()]
    assert all(ids == id_sets[0] for ids in id_sets), "personas diverged on evidence"
    assert len(id_sets[0]) > 10, "a card with almost no query ids proves nothing"


def test_ranked_and_rejected_are_byte_identical_across_personas(cards):
    """Prose may differ. The ranking may not."""
    ref = cards["analyst"]
    for pid, card in cards.items():
        assert [h.hypothesis_id for h in card.ranked] == [h.hypothesis_id for h in ref.ranked], pid
        assert [h.total for h in card.ranked] == [h.total for h in ref.ranked], pid
        assert [h.hypothesis_id for h in card.rejected] == [h.hypothesis_id for h in ref.rejected], pid


def test_default_persona_reproduces_todays_card(payload):
    """The regression guard on the whole refactor: no persona argument must render
    exactly what the analyst persona renders."""
    default = narrate.narrate(payload)
    analyst = narrate.narrate(payload, persona=personas.get("analyst"))
    assert default.summary == analyst.summary
    assert default.headline == analyst.headline
    assert [a.action for a in default.actions] == [a.action for a in analyst.actions]


def test_cfo_prose_never_leaks_an_event_id(cards):
    """'No SQL jargon, no event ids in prose' -- the CFO template's whole job."""
    cfo = cards["cfo"]
    text = f"{cfo.headline} {cfo.summary} " + " ".join(a.action for a in cfo.actions)
    assert "deploy_sepa_v214" not in text
    assert "query_id" not in text
    assert "Jaccard" not in text


def test_cfo_headline_leads_with_money(cards):
    assert "$" in cards["cfo"].headline


def test_oncall_headline_leads_with_the_event_id(cards):
    assert cards["oncall"].headline.startswith("deploy_sepa_v214")


def test_cfo_sees_fewer_actions_than_the_analyst(cards):
    """Persona.max_actions -- 'insight depth personalization' made mechanical."""
    assert len(cards["cfo"].actions) == 2
    assert len(cards["analyst"].actions) > len(cards["cfo"].actions)


def test_cfo_still_gets_the_lever_it_actually_owns(cards):
    """Truncation must not strip the one action a CFO can act on alone. max_actions=2
    is chosen so the CFO sees the escalation AND hold_forecast, not just one or the
    other -- an escalation with nothing to do alongside it is a worse card."""
    levers = [a.lever for a in cards["cfo"].actions]
    assert "hold_forecast" in levers


def test_cfo_is_never_told_to_roll_back_a_release(cards):
    """DECISION RIGHTS. A CFO does not hold rollback_release, so any action on that
    lever must render as an escalation, not an instruction."""
    cfo_actions = " ".join(a.action for a in cards["cfo"].actions)
    assert "Roll back" not in cfo_actions


def test_oncall_is_told_to_roll_back_directly(cards):
    """The mirror image: on-call DOES hold the lever, so no escalation wrapper."""
    p0 = next(a for a in cards["oncall"].actions if a.priority == "P0")
    assert p0.lever == "rollback_release"
    assert not p0.action.startswith("Escalate")


def test_escalation_names_the_owner(cards):
    """An escalation a reader cannot route is useless."""
    for a in cards["growth"].actions:
        if a.action.startswith("Escalate"):
            assert a.owner in a.action


def test_every_persona_abstains_together(payload):
    """Abstention is evidence-driven, so it cannot vary by audience. A CFO must not
    be given a confident answer the analyst was refused."""
    import dataclasses

    abstained = dataclasses.replace(payload, no_confident_cause=True)
    for pid in PERSONA_IDS:
        card = narrate.narrate(abstained, persona=personas.get(pid))
        assert card.no_confident_cause is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_narrate_personas.py -q`
Expected: FAIL — `TypeError: narrate() got an unexpected keyword argument 'persona'`

- [ ] **Step 3: Thread persona through `narrate`**

```python
def narrate(
    payload: NarrationPayload,
    persona: personas.Persona | None = None,
    no_confident_cause: bool | None = None,
) -> DiagnosisCard:
    who = persona or personas.get(personas.DEFAULT_PERSONA_ID)
    abstain = payload.no_confident_cause if no_confident_cause is None else no_confident_cause
    if abstain or not payload.ranked:
        return _no_cause_card(payload, who)
    return _cause_card(payload, who)
```

- [ ] **Step 4: Add the decision-rights router**

```python
def _route(action: Action, who: personas.Persona) -> Action:
    """Decision rights, made mechanical.

    A persona that does not hold the lever is shown an ESCALATION rather than an
    instruction. Priority, owner, evidence and confidence are untouched -- only the
    imperative changes, because who may pull a lever is a fact about the org, not
    about the evidence.
    """
    if personas.holds(who, action.lever):
        return action
    body = action.action[0].lower() + action.action[1:]
    return action.model_copy(update={"action": f"Escalate to {action.owner}: {body}"})


def _for_persona(actions: list[Action], who: personas.Persona) -> list[Action]:
    return [_route(a, who) for a in actions][: who.max_actions]
```

**Also make the action text itself persona-aware.** `_route` alone is not enough: the P0 action string built in Task B contains `top.event.event_id`, so an escalated CFO action would read *"Escalate to the team owning the service: roll back deploy_sepa_v214…"* — which leaks a sha into a card whose whole contract is that it never shows one, and would fail `test_cfo_prose_never_leaks_an_event_id`.

Extract the action construction from `_cause_card` into `_actions(payload, who)` — same four `Action(...)` sites from Task B, moved verbatim except that each one opens with:

```python
    # How this change is named to THIS reader. Personas with show_event_ids=False
    # get the driver phrase; the evidence in `basis` is identical either way.
    ref = top.event.event_id if who.show_event_ids else _driver_label(top.event.event_type)
```

and then uses `ref` everywhere the Task B version used `top.event.event_id` — in `driver`, in `action`, and nowhere else. `basis`, `expected_impact`, `confidence` and `monitoring` are untouched: those carry the evidence, and the evidence does not vary by audience.

The P2 site does the same with its own `ref` derived from `rejected.event`.

- [ ] **Step 5: Add the persona prose templates**

In `_cause_card`, keep every existing computation (`steps`, `unexplained`, `cohort`) exactly as it is — those are the evidence. Replace only the `headline` / `summary` assignment and the `actions=` argument (the action list now comes from the `_actions(payload, who)` helper extracted in Step 4):

```python
    headline, summary = _prose(payload, who, unexplained, cohort)
    ...
    return DiagnosisCard(
        headline=headline,
        summary=summary,
        ...
        actions=_for_persona(_actions(payload, who), who),
        ...
    )
```

And add, next to `_cause_card`:

```python
def _prose(
    payload: NarrationPayload, who: personas.Persona, unexplained: float, cohort: str
) -> tuple[str, str]:
    """Persona-specific headline and summary. NOTHING here computes a number --
    every figure is read off the payload, which is shared across all personas."""
    top = payload.ranked[0]
    focal, root = payload.focal, payload.root
    n_pass = sum(1 for c in top.controls if c.passed)

    if who.persona_id == "cfo":
        headline = (
            f"{payload.metric.replace('_', ' ').title()}: {_money(root.delta_abs)} below plan "
            f"for {root.window.start} to {root.window.end}"
        )
        summary = (
            f"{payload.metric.replace('_', ' ')} came in {_money(root.delta_abs)} "
            f"({root.delta_pct:.1f}%) under baseline for {root.window.start} to "
            f"{root.window.end}. About {abs(payload.seasonal_pct):.1f} points of that is "
            f"normal August seasonality. The remaining {abs(unexplained):.1f} points sit "
            f"almost entirely in one customer group -- {cohort} -- which is "
            f"{_money(focal.delta_abs)} short against its own baseline. "
            f"{_driver_label(top.event.event_type).capitalize()} is the leading explanation; "
            f"it survived every check run against it. Treat the shortfall as at-risk "
            f"revenue, not lost revenue, until the fix ships. "
            f"This ranks evidence; it does not prove causation."
        )
        return headline, summary

    if who.persona_id == "oncall":
        headline = (
            f"{top.event.event_id} -- {cohort} {payload.metric} down "
            f"{abs(focal.delta_pct):.0f}%"
        )
        summary = (
            f"{top.event.event_id} ({top.event.description}) went out "
            f"{top.event.ts_start:%Y-%m-%d %H:%M}. Declared blast radius: "
            f"{cohort_label(top.event.blast_radius)}. {payload.metric} in {cohort} is "
            f"{focal.delta_pct:.0f}% below baseline from {focal.window.start}, "
            f"{_money(focal.delta_abs)} over {focal.window.days} days. Score {top.total:.2f}; "
            f"{n_pass}/{len(top.controls)} negative controls pass. Rollback is the P0. "
            f"This ranks evidence; it does not prove causation."
        )
        return headline, summary

    if who.persona_id == "growth":
        headline = (
            f"{cohort} {payload.metric} down {abs(focal.delta_pct):.0f}% -- "
            f"not attributable to campaign spend"
        )
        rejected_line = (
            f"The DACH budget cut was tested as a cause and rejected outright: "
            f"{payload.rejected[0].rejection_reason} "
            if payload.rejected
            else ""
        )
        summary = (
            f"{payload.metric} in {cohort} is {focal.delta_pct:.0f}% below baseline "
            f"({_money(focal.delta_abs)}). {rejected_line}"
            f"The leading explanation is {_driver_label(top.event.event_type)} affecting "
            f"how that group pays, not demand. The budget cut is still doing what it was "
            f"designed to do to acquisition -- see the P2 below. "
            f"This ranks evidence; it does not prove causation."
        )
        return headline, summary

    # analyst -- today's card, unchanged
    headline = (
        f"{payload.metric} in {cohort} down {abs(focal.delta_pct):.0f}% -- most consistent "
        f"with {top.event.event_id}"
    )
    summary = (
        f"{payload.metric} is {root.delta_pct:.1f}% below baseline for "
        f"{root.window.start} to {root.window.end}. Roughly {payload.seasonal_pct:.1f}% of that "
        f"is August seasonality; the remaining {unexplained:.1f}% concentrates almost entirely "
        f"in {cohort}, which is down {focal.delta_pct:.0f}% and {_money(focal.delta_abs)} against "
        f"its own baseline. Of {len(payload.ranked) + len(payload.rejected)} recorded changes "
        f"whose blast radius touches that cohort, {top.event.event_id} scores {top.total:.2f} "
        f"and survives all {len(top.controls)} of its negative controls. "
        + (
            f"{payload.rejected[0].event.event_id} is temporally just as plausible but was "
            f"rejected outright: {payload.rejected[0].rejection_reason}."
            if payload.rejected
            else ""
        )
        + " This ranks evidence; it does not prove causation."
    )
    return headline, summary
```

`_no_cause_card(payload, who)` takes the persona too, and applies `_for_persona(...)` to its single action. Its prose is deliberately **not** personalised: abstention says the same thing to everyone.

- [ ] **Step 6: Run the tests**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_narrate_personas.py -q`
Expected: PASS, 12 tests

- [ ] **Step 7: Run the full suite**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q`
Expected: `157 passed` (145 + 12)

- [ ] **Step 8: Commit**

```bash
git add ledgerlens/narrate.py tests/test_narrate_personas.py
git commit -m "feat(personas): persona-specific narratives over identical evidence"
```

---

## Task E: Sidebar selector and action rendering

**Files:**
- Modify: `app.py:28-32` (`load`), `app.py:42-46` (sidebar), `app.py:340-343` (actions)
- Modify: `tests/test_app.py:45`

**Interfaces:**
- Consumes: everything from Tasks A–D.
- Produces: nothing downstream; this is the last layer.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_app.py  (append)

def test_persona_selector_is_present(app):
    labels = [s.label for s in app.sidebar.selectbox]
    assert "Persona" in labels


def test_actions_render_the_full_recommendation_chain(app):
    text = " ".join(m.value for m in app.markdown)
    assert "lever:" in text
    assert "expected impact:" in text
    assert "confidence:" in text
    assert "monitoring:" in text


def test_confidence_caption_does_not_overclaim(app):
    """A judge will ask what 0.70 means. The page must answer before they ask."""
    text = " ".join(c.value for c in app.caption)
    assert "not a probability that the action will work" in text
```

Also change `tests/test_app.py:45` from `assert len(scores) == 5` — that assertion counts hypothesis score tiles, not actions, so it is **unchanged by this task**. Verify that before editing it; if it turns out to count actions, update it to the analyst count rather than deleting it.

- [ ] **Step 2: Run the test to verify it fails**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_app.py -q`
Expected: FAIL — `AssertionError: 'Persona' not in [...]`

- [ ] **Step 3: Cache the payload, not the card**

```python
@st.cache_resource(show_spinner="Running diagnosis...")
def load_payload(metric: str, as_of_iso: str):
    """Cached on (metric, as_of) ONLY. Persona is applied after this boundary, which
    is what makes switching persona instant -- and what makes 'identical evidence'
    structurally true rather than a coincidence of determinism.

    Task 4 (role-based entitlement) CANNOT stay below this boundary: hiding a
    dimension changes which cuts are drilled, so it changes the payload. Add `role`
    to this key when Task 4 lands.
    """
    from datetime import date

    store = pipeline.get_store()
    return store, pipeline.diagnose(metric, date.fromisoformat(as_of_iso), store=store)
```

- [ ] **Step 4: Add the selector and render**

Sidebar, immediately after the metric selectbox at `app.py:45`:

```python
persona_id = st.sidebar.selectbox(
    "Persona",
    list(personas.PERSONAS),
    index=list(personas.PERSONAS).index(personas.DEFAULT_PERSONA_ID),
    format_func=lambda pid: personas.get(pid).label,
)
who = personas.get(persona_id)
st.sidebar.caption(
    f"Delivered to **{who.channel}** · depth `{who.depth}` · "
    f"decision rights: {', '.join(who.decision_rights)}"
)
```

Where `card` is currently built:

```python
store, payload = load_payload(metric, as_of.isoformat())
card = (
    narrate.narrate(payload, persona=who)
    if payload is not None
    else DiagnosisCard.no_anomaly(metric, as_of)
)
```

Add `narrate` and `personas` to the `from ledgerlens import ...` line and `DiagnosisCard` to the models import.

Replace the action block at `app.py:340-343`:

```python
st.markdown("**Recommended actions**")
st.caption(
    f"Shown for **{who.label}**. Confidence is the score of the evidence each action "
    f"rests on -- it is not a probability that the action will work."
)
for a in card.actions:
    st.markdown(f"**[{a.priority}] {a.owner}** — {a.action}")
    st.markdown(
        f"driver: {a.driver}  \n"
        f"lever: `{a.lever}`  \n"
        f"expected impact: {a.expected_impact}  \n"
        f"confidence: {a.confidence:.2f}  \n"
        f"monitoring: {a.monitoring}"
    )
    st.caption(f"basis: {a.basis}")
```

Gate the control table on `who.show_control_table` wherever the per-hypothesis control table is rendered.

- [ ] **Step 5: Run the full suite**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q`
Expected: `160 passed` (157 + 3)

- [ ] **Step 6: Eyeball it**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m streamlit run app.py`
Switch persona four times. The ranking table, the scores and every "show query" expander must be **identical** across all four; only the headline, summary and action list change. If a number moves, stop — the persona layer has leaked into the evidence path.

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat(ui): persona selector; render the full recommendation chain"
```

---

## Task F: Document the claim

**Files:**
- Modify: `README.md`
- Modify: `taskflow/taskflow.md` (tick Task 2)

- [ ] **Step 1: Add a persona section to `README.md`**

Place it directly after "The core primitive: blast radius". It must contain:

1. The four-persona table from §1.4 of this plan.
2. The claim, stated once and plainly: *"Four audiences, one computation. `narrate()` is the only function that knows which persona is reading; the store, the ranker and the controls never see it. `tests/test_narrate_personas.py::test_personas_differ_in_prose_but_share_every_query_id` asserts four different summaries against one identical query-id list."*
3. The `Action` chain, showing that the field order in `models.py` is the brief's order.
4. The decision-rights example, concretely: *"The CFO card never says 'roll back'. It says 'Escalate to the team owning the service: roll back deploy_sepa_v214…' — because `cfo.decision_rights` does not contain `rollback_release`."*
5. The confidence-provenance table from §1.6.

- [ ] **Step 2: Verify the README claims against the code**

Run the demo and paste real output — do not hand-write the CFO summary into the README from this plan. The templates will have drifted during implementation.

```bash
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python - <<'PY'
from ledgerlens import narrate, personas, pipeline
p = pipeline.diagnose()
for pid in ("analyst", "cfo", "oncall", "growth"):
    c = narrate.narrate(p, persona=personas.get(pid))
    print(f"\n=== {pid} ===\n{c.headline}\n{c.summary}")
    for a in c.actions:
        print(f"  [{a.priority}] {a.action}  (conf {a.confidence:.2f}, lever {a.lever})")
print("\nquery ids identical:", len({tuple(pipeline.card_query_ids(narrate.narrate(p, persona=personas.get(x)))) for x in ("analyst","cfo","oncall","growth")}) == 1)
PY
```

- [ ] **Step 3: Mark Task 2 done in `taskflow/taskflow.md`** and note that Task 4 is now unblocked — `Persona.role` is live and `contracts.visible_drill_dims(role)` already exists; Task 4 is the wiring plus a test.

- [ ] **Step 4: Full suite, then commit**

```bash
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q
git add README.md taskflow/taskflow.md
git commit -m "docs: persona layer, decision rights, and the confidence provenance table"
```

---

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| **Persona leaks into the evidence path.** | Kills the entire pitch, silently. A judge who spots a number moving between personas has found the one flaw that matters. | `test_ranked_and_rejected_are_byte_identical_across_personas` plus Task E Step 6 (eyeball). Treat a failure as a design bug, never as a test to relax. |
| **`test_app.py` breaks on the `Action` reshape (Task B) before the renderer exists (Task E).** | Tasks B–E are a chain; the UI is stale in the middle of it. | Expected. xfail with an explicit `reason="renders in Task E"` and clear the mark in Task E. Do not skip. |
| **CFO template leaks an event id after a later edit.** | The "no jargon" claim is only as good as the last person to touch the template. | `test_cfo_prose_never_leaks_an_event_id` asserts on the literal string `deploy_sepa_v214`. It will catch a copy-paste from the analyst template. |
| **`confidence` reads as a probability.** | Overclaiming is the one thing this project has consistently refused to do; a stray 0.70 labelled "confidence" undoes that. | The §1.6 table in the README, plus the UI caption, plus `test_confidence_caption_does_not_overclaim`. |
| **Scope creep into Task 4.** | `growth`'s `role` is live and `contracts.visible_drill_dims()` is sitting right there. Very tempting. | Task 2 ships `Persona.role` and stops. Entitlement enforcement is Task 4 and gets its own tests. |
| **The `@st.cache_resource` key debt is only half paid.** | Task E moves the cache boundary below narration, which solves persona but not entitlement. Task 4 changes the payload, so a stale cache would serve a `growth` user a card containing the dimension they are not entitled to see. | Global Constraints and the `load_payload` docstring both say so explicitly. Task 4 adds `role` to the key. |

## Estimate

`taskflow.md` budgets 3h. Tasks A–D are ~2h; E is ~40m; F is ~30m. Task C is the one that can overrun — it is a refactor of the only function every test depends on. If it goes sideways, `narrate(payload, persona=...)` still works without it; the cost is a slower persona switch in the UI and a weaker version of the "one computation" claim.
