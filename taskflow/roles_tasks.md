# Task 4 — Role-Based Entitlement: Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking. Every task
> is a full red→green→commit cycle. Do not write implementation before its test fails.

**Goal:** Make `payment_rail` cuts of `mrr_renewals` genuinely invisible to the
`growth` role, and make the withholding *visible and attributable* — the card names the
policy that redacted it and the reason, so a refusal reads as governance rather than as
a missing feature.

**Architecture:** Entitlement is enforced at exactly one place — the list of dimensions
handed to `anomaly.drill()`. Everything downstream (focal selection, hypothesis ranking,
controls, narration) is unchanged and unaware. The withheld dimensions travel forward as
a `Redaction` list on the payload and the card, so narration can state the refusal
without recomputing anything. Role enters the pipeline **above** the caching boundary,
because it changes the payload.

**Tech stack:** Python 3.12, Pydantic v2 (frozen models), DuckDB, Streamlit, pytest.

**Spec:** [`taskflow/taskflow.md`](taskflow.md) § "Task 4 — Role-based entitlement".
Closes **Minimum Prototype Expectation row 7** (*"One role-based security or entitlement
scenario"*) — the only uncovered row on that list.

## Global constraints

- **Every number reaches the UI through `Store.q()`.** A redaction notice is *not* a
  number and carries no `query_id`; it must never be smuggled in as an `EvidenceStep`.
- **Pydantic models are `frozen=True`.** Build new objects, never mutate.
- **`NarrationPayload` is a `@dataclass`, not a Pydantic model.** New fields need a
  `field(default_factory=...)` and must come after existing defaulted fields.
- **Narration computes nothing.** `_cause_card` copies figures off the payload.
- Run tests as: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q`
- **The suite count is asserted.** `tests/test_docs.py::test_readme_test_count_is_true`
  compares `README.md` against `pytest --collect-only`. Task 4 adds tests, so the README
  must be updated in the final task or the suite goes red. Baseline today: **184**.

---

## Jargon — the words this task uses, and what they actually mean here

| Term | Meaning in this codebase |
|---|---|
| **Entitlement** | Which *cuts* (dimension slices) of a KPI a role may see. Dimension-level only. |
| **Row-level security** | Filtering which *rows* a role may see. **Explicitly out of scope** — `AccessRule`'s docstring says so. We hide the `payment_rail` breakdown; we do not hide sepa revenue from the totals. |
| **`AccessRule`** | `(policy_id, role, hidden_dims, reason)` on a `KpiContract`. One is already declared: `fin.rail_detail` hides `payment_rail` from `growth` on `mrr_renewals`. |
| **`policy_id`** | The stable name of the rule (`"fin.rail_detail"`). Rendered verbatim; never hardcoded in prose. |
| **Fail-open** | A role with no matching `AccessRule` is unrestricted. Deliberate: the sensitive surface is a named subset of dimensions, not the metric. Fail-closed would blank the page for every unnamed role. |
| **`DRILL_DIMS`** | `["region", "segment", "payment_rail", "product"]` — the dimensions `drill()` may expand. Entitlement is subtraction from this list. |
| **`visible_drill_dims(role)`** | `DRILL_DIMS` minus `hidden_dims_for(role)`. **Already written and tested** in `contracts.py:195`. Task 4 is mostly about *calling* it. |
| **Focal cohort** | The deepest, highest-path-contribution node from `drill()`. The headline number is the focal's. Hiding a dimension changes which node this is — see "The measurement" below. |
| **Payload boundary** | `pipeline.diagnose()` returns a `NarrationPayload`; `narrate.narrate()` turns it into a card. Persona lives *below* the boundary (rendering only). **Role lives above it** (it changes the computation). |
| **Cache key** | `app.py`'s `@st.cache_resource` on `load_payload`. Anything that changes the *payload* must join this key. |
| **Redaction** | A record that a dimension was withheld: `(dim, policy_id, reason)`. New in this task. |

---

## The measurement — run before planning, not guessed

The single highest-risk unknown was what actually happens to the answer when
`payment_rail` is removed. Measured against the live store:

| | `analyst` (all 4 dims) | `growth` (3 dims, no `payment_rail`) |
|---|---|---|
| nodes returned | 4 | 6 |
| **focal cohort** | `DACH · Enterprise · sepa` | **`DACH · Enterprise · A`** |
| focal Δ% | **−85.2%** | **−34.6%** |
| focal Δ$ | **−$416,144** | **−$207,545** |
| nodes naming `payment_rail` | 1 | **0** |
| ranked order | `deploy_sepa_v214`, `deploy_dunning_v3`, `deploy_billing_ui_v9`, `flag_sepa_retry_beta` | **identical order** |
| top score | **0.700** | **0.627** |
| rejected | `campaign_dach_cut` | `campaign_dach_cut` |
| clears `SCORE_FLOOR` (0.45)? | yes | **yes** |

**Three things this settles:**

1. The taskflow's risk note is correct — the headline number *does* change for `growth`,
   from −$416k to −$208k. This is right (a shallower cut of the same anomaly), but it
   will look like a bug on stage unless the redaction line explains it.
2. **Growth still gets a confident card.** The top candidate clears the score floor, so
   entitlement does **not** accidentally trigger the abstention path. Task 4 and Task 7
   stay independent.
3. **Scores change; order does not.** `deploy_sepa_v214` scores 0.700 for the analyst and
   0.627 for growth, because `hypothesis.rank()` scores against the *focal* cohort and
   the focal moved. This directly contradicts the docstring on one of the taskflow's
   proposed tests — see Correction 1.

---

## Three corrections to the taskflow's draft

The plan in `taskflow.md` § Task 4 was written before the code was probed. Three of its
snippets do not survive contact.

### Correction 1 — `test_redaction_does_not_change_the_ranking_inputs` has a false docstring

Draft docstring: *"The candidate set and their **scores** must be identical."*
**The scores are not identical** (0.700 vs 0.627), and they should not be — the focal
cohort legitimately differs. The assertion body (comparing `event_id` order) passes and
is worth keeping; the docstring would lure a future reader into "strengthening" the test
into a guaranteed failure. Rewritten in Task 4.4 to claim only what is true: the
candidate *set and its order* are stable, so entitlement never silently reorders the
answer.

### Correction 2 — the draft calls the *strict* contract lookup from the engine

Draft: `contracts.get(metric).visible_drill_dims(role)`.
`contracts.get()` **raises** on an ungoverned KPI. `contracts.py:398` splits this
deliberately: the UI refuses to render an ungoverned KPI, but *"detection must not crash
because metadata is missing"*. Calling the strict lookup inside `diagnose()` inverts
that. Use `contracts.CONTRACTS.get(metric)` and fall back to `config.DRILL_DIMS`, exactly
as `contracts.thresholds()` falls back to global defaults. (No live crash today — all
three KPIs are contracted — but it breaks a documented invariant.)

### Correction 3 — `pipeline.run()` has no `persona` parameter

The draft's `test_redaction_names_its_policy` calls
`pipeline.run(..., persona=personas.get("growth"))`. `run()`'s signature is
`(metric, as_of, store, cohort, window)` and it calls `narrate.narrate(payload)` with no
persona — that test raises `TypeError` as written. Task 4.3 adds `role` **and** `persona`
to `run()`.

---

## Decisions

**D1 — Enforce at `drill()`, nowhere else.**
One chokepoint. `hypothesis`, `controls` and `narrate` stay unaware of roles, so there is
no second place for the policy to be forgotten. The cost is that entitlement is only as
good as the dimension list — accepted, and stated in D7.

**D2 — `Redaction` is a frozen Pydantic model, not a `tuple[str, str, str]`.**
The draft proposed a bare 3-tuple. Every cross-module payload in this project is a
Pydantic model (`contracts.py`'s own docstring gives the reason: a mistyped field fails
at import, not on stage). `r.policy_id` also survives reordering in a way `r[1]` does not.

**D3 — A redaction is NOT an `EvidenceStep`.**
`EvidenceStep.query_id` is required, and there is no query behind a policy decision.
Faking one with `query_id=""` would put a claim with no provenance into the evidence
chain — the exact thing this product's pitch forbids. `redactions` is its own field on
`DiagnosisCard`, rendered into the summary prose and as its own UI banner. This mirrors
the carve-out the taskflow already grants telemetry in Task 6.

**D4 — Do not count the hidden slices.**
The draft's copy reads *"**2 deeper slices** redacted by policy `fin.rail_detail`"*.
Producing that count requires running the unrestricted drill — i.e. computing exactly
the result the role is not entitled to, and holding it in the same process that renders
their page. A redaction notice that must first compute the secret is not a redaction.
The line names the **dimension, policy id and reason** — all free, all from the
`AccessRule`. (For the record, the true count is 1, not 2.)

**D5 — `role=None` means unrestricted, and is the default.**
Preserves every existing call site byte-for-byte. `role="analyst"` resolves to the full
`DRILL_DIMS` anyway (fail-open, no rule matches), so the default persona's card is
unchanged — which is what keeps `tests/test_app.py`'s `scores[0] == "0.700"` green.

**D6 — Role is derived from the persona, not chosen separately.** *(open — see below)*
`Persona.role` already exists and `tests/test_personas.py:39` already asserts
`growth`'s role joins the contract's `AccessRule`. Threading `who.role` is the smallest
correct change and makes entitlement real rather than a demo switch.
**Consequence:** the demo beat *"same evidence, four audiences — the query ids are
identical"* becomes **false for `growth`**, who now gets a genuinely different (shallower)
payload. It stays true for `analyst`/`cfo`/`oncall`.
`tests/test_narrate_personas.py` does **not** break — it renders four personas from one
role-free payload, which is still a valid and meaningful invariant ("at a fixed
entitlement, prose differs and evidence does not"). But the *script* must change.
See "Decision needed from you" at the foot of this file.

**D7 — Manual cohort selection is not entitlement-checked. Documented, not fixed.**
`app.py`'s manual-window path builds `{"region": [...], "payment_rail": ["sepa"]}`
directly, bypassing `drill()`. That path is reachable only for `status="sparse_history"`
KPIs — today only `payment_success_rate`, which declares **no** `AccessRule` — so there is
no live leak. It is still a hole in the shape of the feature, and it goes in the module
docstring and the business proposal's roadmap rather than being quietly left out.

**D8 — Redactions are computed from the contract, not inferred from the dim list.**
Populate from `contract.access` matching the role, so `policy_id` and `reason` are the
declared strings. Never reconstruct "what's missing from DRILL_DIMS" — that would report
a redaction with no policy behind it.

---

## File structure

| File | Change |
|---|---|
| `ledgerlens/models.py` | **Add** `Redaction` model; add `redactions` field to `DiagnosisCard`. |
| `ledgerlens/pipeline.py` | `diagnose()` and `run()` gain `role`; select dims; build redactions. |
| `ledgerlens/narrate.py` | `NarrationPayload` gains `redactions`; `_cause_card`/`_no_cause_card` pass through and append the policy sentence. |
| `app.py` | Pass `who.role` into `load_payload`; **add `role_key` to the cache key**; render the redaction banner. |
| `tests/test_entitlement.py` | **New.** The whole task's assertions. |
| `README.md`, `CLAUDE.md` | Test count + a short entitlement section. |

---

## Task 4.1 — `Redaction` model and payload/card fields

**Files:** Modify `ledgerlens/models.py`, `ledgerlens/narrate.py`. Test `tests/test_entitlement.py` (create).

**Interfaces produced:**
- `models.Redaction(dim: str, policy_id: str, reason: str)` — frozen.
- `models.DiagnosisCard.redactions: list[Redaction] = []`
- `narrate.NarrationPayload.redactions: list[Redaction]` (default empty)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_entitlement.py
"""Role-based entitlement: redaction WITH provenance.

The point is not that growth sees less. It is that growth is TOLD it sees less,
by which policy, and why -- a refusal that names itself is governance; a silently
shorter answer is a bug.
"""

from __future__ import annotations

import config
from ledgerlens import contracts, narrate, personas, pipeline
from ledgerlens.models import DiagnosisCard, Redaction


def test_redaction_carries_dim_policy_and_reason():
    r = Redaction(dim="payment_rail", policy_id="fin.rail_detail", reason="finance-restricted")
    assert (r.dim, r.policy_id) == ("payment_rail", "fin.rail_detail")


def test_cards_default_to_no_redactions():
    """Every existing construction site stays valid: the field is defaulted."""
    card = DiagnosisCard.no_anomaly("mrr_renewals", pipeline.DEFAULT_AS_OF)
    assert card.redactions == []
```

- [ ] **Step 2: Run it and watch it fail**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_entitlement.py -q`
Expected: `ImportError: cannot import name 'Redaction' from 'ledgerlens.models'`

- [ ] **Step 3: Implement**

In `ledgerlens/models.py`, beside `EvidenceStep`:

```python
class Redaction(BaseModel):
    """A dimension withheld from this reader by policy.

    Deliberately NOT an EvidenceStep: that model requires a `query_id`, and there is
    no query behind a policy decision. Putting a provenance-free claim into the
    evidence chain would break the one invariant this product rests on.
    """

    model_config = ConfigDict(frozen=True)
    dim: str
    policy_id: str
    reason: str
```

On `DiagnosisCard`, after `no_confident_cause`:

```python
    redactions: list[Redaction] = []
```

In `ledgerlens/narrate.py`, import `Redaction` alongside the other models, and add to
`NarrationPayload` **after** `no_confident_cause` (dataclass ordering — defaulted fields
must follow defaulted fields):

```python
    redactions: list[Redaction] = field(default_factory=list)
```

Add `field` to the existing dataclasses import: `from dataclasses import dataclass, field`.

- [ ] **Step 4: Run and verify green**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_entitlement.py -q`
Expected: 2 passed.

- [ ] **Step 5: Full suite (nothing else may move)**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q`
Expected: 186 passed.

- [ ] **Step 6: Commit**

```bash
git add ledgerlens/models.py ledgerlens/narrate.py tests/test_entitlement.py
git commit -m "feat(models): Redaction -- a withheld dimension, with the policy that withheld it"
```

---

## Task 4.2 — Thread `role` into `diagnose()`

**Files:** Modify `ledgerlens/pipeline.py:31-82`. Test `tests/test_entitlement.py`.

**Interfaces consumed:** `models.Redaction` (4.1), `contracts.KpiContract.visible_drill_dims`.
**Interfaces produced:** `pipeline.diagnose(..., role: str | None = None)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_growth_never_sees_a_payment_rail_cut(store):
    payload = pipeline.diagnose(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="growth"
    )
    assert payload is not None
    assert all("payment_rail" not in n.cohort for n in payload.nodes)


def test_analyst_still_sees_every_cut(store):
    payload = pipeline.diagnose(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="analyst"
    )
    assert any("payment_rail" in n.cohort for n in payload.nodes)


def test_no_role_is_byte_identical_to_the_analyst_role(store):
    """Fail-open, proven: an unrestricted role must not perturb today's card."""
    none_role = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store)
    analyst = pipeline.diagnose(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="analyst"
    )
    assert [n.anomaly_id for n in none_role.nodes] == [n.anomaly_id for n in analyst.nodes]
    assert none_role.focal.anomaly_id == analyst.focal.anomaly_id


def test_diagnose_reports_what_it_withheld(store):
    payload = pipeline.diagnose(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="growth"
    )
    assert [r.dim for r in payload.redactions] == ["payment_rail"]
    assert payload.redactions[0].policy_id == "fin.rail_detail"
    # The reason is the contract's declared string, never prose invented here.
    rule = contracts.get("mrr_renewals").access[0]
    assert payload.redactions[0].reason == rule.reason


def test_an_unrestricted_role_redacts_nothing(store):
    payload = pipeline.diagnose(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="analyst"
    )
    assert payload.redactions == []
```

- [ ] **Step 2: Run and watch them fail**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_entitlement.py -q`
Expected: `TypeError: diagnose() got an unexpected keyword argument 'role'`

- [ ] **Step 3: Implement**

In `pipeline.py`, add `role: str | None = None` to `diagnose()`'s signature (after
`window`), extend the docstring, and replace line 60:

```python
        nodes = anomaly.drill(store, root, _visible_dims(metric, role))
```

Add above `diagnose()`:

```python
def _contract_for_engine(metric: str):
    """LENIENT lookup, matching `contracts.thresholds`. The UI refuses to render an
    ungoverned KPI; the engine must degrade to global defaults rather than crash.
    `contracts.get` is the strict one and does not belong on this path."""
    return contracts.CONTRACTS.get(metric)


def _visible_dims(metric: str, role: str | None) -> list[str]:
    contract = _contract_for_engine(metric)
    if role is None or contract is None:
        return config.DRILL_DIMS
    return contract.visible_drill_dims(role)


def _redactions_for(metric: str, role: str | None) -> list[Redaction]:
    """Read off the contract, never inferred from the dim list -- a redaction with no
    declared policy behind it is exactly the thing we are refusing to emit."""
    contract = _contract_for_engine(metric)
    if role is None or contract is None:
        return []
    return [
        Redaction(dim=dim, policy_id=rule.policy_id, reason=rule.reason)
        for rule in contract.access
        if rule.role == role
        for dim in rule.hidden_dims
    ]
```

Add imports: `from ledgerlens import anomaly, contracts, hypothesis, narrate` and
`from ledgerlens.models import Anomaly, Cohort, DiagnosisCard, Redaction, Window`.

Pass into the returned payload:

```python
        redactions=_redactions_for(metric, role),
```

- [ ] **Step 4: Run and verify green**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_entitlement.py -q`
Expected: 7 passed.

- [ ] **Step 5: Full suite**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q`
Expected: 191 passed, **no failures in `test_pipeline.py` or `test_app.py`**. If
`scores[0] == "0.700"` breaks, D5 is violated — the default path took a role somewhere.

- [ ] **Step 6: Commit**

```bash
git add ledgerlens/pipeline.py tests/test_entitlement.py
git commit -m "feat(pipeline): entitlement at the drill boundary, with the policy recorded"
```

---

## Task 4.3 — Narrate the refusal

**Files:** Modify `ledgerlens/narrate.py`, `ledgerlens/pipeline.py`. Test `tests/test_entitlement.py`.

**Interfaces produced:** `pipeline.run(..., role=None, persona=None)`; cards carry `redactions`.

- [ ] **Step 1: Write the failing tests**

```python
def test_redaction_names_its_policy_on_the_card(store):
    card = pipeline.run(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store,
        role="growth", persona=personas.get("growth"),
    )
    assert [r.policy_id for r in card.redactions] == ["fin.rail_detail"]
    assert "fin.rail_detail" in card.summary
    assert "payment_rail" in card.summary


def test_the_redaction_line_is_not_hardcoded_prose(store):
    """policy_id and reason come off the AccessRule. If someone retypes them into
    narrate.py, changing the contract stops changing the card -- and the governance
    story becomes decoration."""
    card = pipeline.run(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store,
        role="growth", persona=personas.get("growth"),
    )
    reason = contracts.get("mrr_renewals").access[0].reason
    assert reason.rstrip(".") in card.summary


def test_an_entitled_reader_sees_no_redaction_language(store):
    card = pipeline.run(
        "mrr_renewals", pipeline.DEFAULT_AS_OF, store=store,
        role="analyst", persona=personas.get("analyst"),
    )
    assert card.redactions == []
    assert "redact" not in card.summary.lower()


def test_redaction_does_not_reorder_the_candidates(store):
    """Entitlement hides CUTS, not candidates. The scores DO move -- the focal cohort
    legitimately changes, so hypothesis.rank scores against a different slice
    (0.700 -> 0.627 for deploy_sepa_v214). What must not move is the candidate set or
    its order: a policy that silently promoted a different cause would be a security
    hole dressed as a feature.
    """
    a = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="analyst")
    g = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="growth")
    assert [h.event.event_id for h in a.ranked] == [h.event.event_id for h in g.ranked]
    assert [h.event.event_id for h in a.rejected] == [h.event.event_id for h in g.rejected]


def test_entitlement_does_not_trigger_abstention(store):
    """Measured: growth's top candidate still clears SCORE_FLOOR. If this ever goes
    red, a redacted reader is being shown the 'no connected change explains it' card,
    which would blame the data for what policy did."""
    g = pipeline.diagnose("mrr_renewals", pipeline.DEFAULT_AS_OF, store=store, role="growth")
    assert g.no_confident_cause is False
    assert g.ranked[0].total >= config.SCORE_FLOOR
```

- [ ] **Step 2: Run and watch them fail**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_entitlement.py -q`
Expected: `TypeError: run() got an unexpected keyword argument 'role'`

- [ ] **Step 3: Implement**

In `pipeline.py`, `run()` gains `role: str | None = None` and
`persona: "personas.Persona | None" = None`, and forwards both:

```python
    payload = diagnose(metric, as_of, store=store, cohort=cohort, window=window, role=role)
    if payload is None:
        return DiagnosisCard.no_anomaly(metric, as_of)
    return narrate.narrate(payload, persona=persona)
```

In `narrate.py`, add a helper above `_cause_card`:

```python
def _redaction_sentence(payload: NarrationPayload) -> str:
    """One sentence per policy, built from the AccessRule's own strings.

    Deliberately does NOT count the hidden slices: producing that count means running
    the unrestricted drill, i.e. computing the very answer this reader is not entitled
    to. The dimension, the policy id and the reason are enough to make the refusal
    attributable, and they are free.
    """
    if not payload.redactions:
        return ""
    by_policy: dict[str, list[str]] = {}
    reasons: dict[str, str] = {}
    for r in payload.redactions:
        by_policy.setdefault(r.policy_id, []).append(r.dim)
        reasons[r.policy_id] = r.reason
    out = []
    for policy_id, dims in by_policy.items():
        cuts = ", ".join(f"`{d}`" for d in sorted(set(dims)))
        out.append(
            f" Deeper cuts by {cuts} are redacted from this view by policy "
            f"`{policy_id}`: {reasons[policy_id].rstrip('.')}. The figures above are "
            f"the most specific slice you are entitled to, not the most specific slice "
            f"that exists."
        )
    return "".join(out)
```

Append it to the summary in **both** `_cause_card` and `_no_cause_card`, and pass the
list through to the card. In `_cause_card`, after `headline, summary = _prose(...)`:

```python
    summary = summary + _redaction_sentence(payload)
```

and add `redactions=payload.redactions,` to both `DiagnosisCard(...)` constructions.

- [ ] **Step 4: Run and verify green**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_entitlement.py -q`
Expected: 12 passed.

- [ ] **Step 5: Full suite**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q`
Expected: 196 passed. `test_narrate_personas.py` must stay green — it renders one
role-free payload four ways, so no redaction language appears in any of them.

- [ ] **Step 6: Commit**

```bash
git add ledgerlens/pipeline.py ledgerlens/narrate.py tests/test_entitlement.py
git commit -m "feat(narrate): state the redaction, name the policy, cite the reason"
```

---

## Task 4.4 — Wire it to the UI and pay the cache-key debt

**Files:** Modify `app.py:30-52`, `app.py:128`. Test `tests/test_app.py`.

This is the half of the cache-key debt that
[`docs/persona_decisions.md`](../docs/persona_decisions.md) §10 left unpaid, and that
`load_payload`'s docstring warns about. **Fix the signature once here**, leaving room for
Task 7's `drop_sources`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_app.py -- append
def test_growth_persona_card_names_the_redaction_policy(truth):
    """The UI half of MPE row 7: switching persona to growth must visibly redact."""
    at = AppTest.from_file(APP_PATH, default_timeout=180).run()
    at.sidebar.selectbox[1].select("growth").run()
    text = " ".join(m.value for m in at.markdown) + " ".join(
        w.value for w in at.warning
    )
    assert "fin.rail_detail" in text
    assert at.exception == []
```

- [ ] **Step 2: Run and watch it fail**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_app.py -q -k redaction`
Expected: FAIL — `fin.rail_detail` not in the rendered text.

> If the selectbox index is wrong, print `[s.label for s in at.sidebar.selectbox]` and
> select by label rather than guessing the index.

- [ ] **Step 3: Implement**

Rewrite `load_payload`'s signature and docstring:

```python
@st.cache_resource(show_spinner="Running diagnosis...")
def load_payload(
    metric: str,
    as_of_iso: str,
    cohort_key: str = "",
    window_key: str = "",
    role_key: str = "",
):
    """Cached on everything that changes the PAYLOAD.

    The boundary rule: persona is a rendering concern and lives BELOW this function,
    which is why switching persona is instant. Role is not -- entitlement changes
    which dimensions are drilled, so it changes the numbers, so it must join the key.
    Task 7's `drop_sources` is the same shape and goes here too.
    """
    ...
    return store, pipeline.diagnose(
        metric,
        date.fromisoformat(as_of_iso),
        store=store,
        cohort=cohort,
        window=window,
        role=role_key or None,
    )
```

At the call site (`app.py:128`):

```python
store, payload = load_payload(
    metric, as_of.isoformat(), cohort_key, window_key, who.role
)
card = (
    narrate.narrate(payload, persona=who)
    if payload is not None
    else DiagnosisCard.no_anomaly(metric, as_of)
)
```

Render the banner immediately after the four headline metrics, where the changed number
is — not buried in the contract expander:

```python
if card.redactions:
    st.warning(
        "🔒 **Restricted view.** "
        + " ".join(
            f"`{r.dim}` cuts are hidden from role `{who.role}` by policy "
            f"`{r.policy_id}` — {r.reason}"
            for r in card.redactions
        )
        + "  \nThe headline above is the deepest slice this role may see. An "
        "entitled reader sees a narrower cohort and a larger shortfall."
    )
```

- [ ] **Step 4: Run and verify green**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest tests/test_app.py -q`
Expected: all pass, including the pre-existing `scores[0] == "0.700"` (default persona is
`analyst`, so the default view is unchanged).

- [ ] **Step 5: Eyeball it**

Run: `env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m streamlit run app.py`
Confirm: switching persona to **Growth Marketing** changes the focal cohort to
`DACH · Enterprise · A`, shows −$207,545, and displays the 🔒 banner naming
`fin.rail_detail`. Switching back to **Revenue Analyst** restores
`DACH · Enterprise · sepa` and −$416,144.

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat(ui): entitled views, and the cache key that makes them correct"
```

---

## Task 4.5 — Make the claims true (the Task 0 discipline)

**Files:** `README.md`, `CLAUDE.md`, `docs/persona_decisions.md`.

- [ ] **Step 1: Get the real count**

```bash
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest --collect-only -q | tail -2
```

- [ ] **Step 2: Update both README claims** (`README.md:46`, `README.md:268`) to that
      number. Do not guess it — `tests/test_docs.py` compares them.

- [ ] **Step 3: Add a short README section** under the entitlement heading: the policy,
      the role, what changes, and the honest note that the growth headline is a
      *different, shallower* number by design.

- [ ] **Step 4: Update `CLAUDE.md`** — current state (task 4 done), and strike the
      cache-key debt note, which this task pays.

- [ ] **Step 5: Note D7's gap** in `docs/persona_decisions.md` §10 — manual cohort
      selection is not entitlement-checked, unreachable today, roadmap item.

- [ ] **Step 6: Full suite + commit**

```bash
env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python -m pytest -q
git add README.md CLAUDE.md docs/persona_decisions.md
git commit -m "docs: entitlement scenario, and the test count it moved"
```

---

## Risks

| Risk | Mitigation |
|---|---|
| **The growth headline number changes** (−$416k → −$208k). Looks like a bug on stage. | The 🔒 banner and the summary sentence. **Do not ship the dim-hiding without the banner** — that is the whole task. |
| A reviewer "strengthens" the ranking test to compare scores. | Correction 1's docstring says explicitly why scores differ. |
| `test_app.py`'s `scores[0] == "0.700"` breaks. | Means D5 was violated. Default persona is `analyst` → unrestricted → identical payload. |
| Cache returns a stale payload when persona flips. | `role_key` is in the key. Verified manually in 4.4 Step 5. |
| `drill()`'s `-dims.index(d)` tiebreak shifts. | Removing `payment_rail` preserves the *relative* order of `region`/`segment`/`product`, so tie resolution is unchanged. Measured: ranked order identical. |
| Entitlement silently triggers abstention. | `test_entitlement_does_not_trigger_abstention` asserts the measured 0.627 ≥ 0.45. |

---

## Decision needed from you before I start

**D6 — should `growth`'s entitlement be tied to the persona selector, or be its own control?**

- **(a) Tied to persona (recommended, and what this plan is written for).** Selecting
  "Growth Marketing" genuinely redacts. Entitlement is real, not a demo toggle, and it
  reuses `Persona.role`, which already exists and is already tested. **Cost:** the demo
  beat *"same evidence, four audiences, identical query ids"* is no longer true for
  growth — beat 5 of the video script needs one extra sentence, and beat 7 becomes its
  payoff rather than a separate scene.
- **(b) A separate "View as role" sidebar control**, defaulting to unrestricted. Keeps
  the persona beat pristine and gives entitlement its own dedicated beat. **Cost:** an
  extra control on screen, and entitlement reads as a switch someone flips rather than
  as policy that is simply in force.

I recommend **(a)**. It is the honest reading of "role-based entitlement scenario", and
the tension it creates is worth naming out loud on stage: *the same engine, the same
evidence, and two readers who are entitled to different depths of it.*

Nothing in this plan has been executed. Say the word and I'll start at Task 4.1.
