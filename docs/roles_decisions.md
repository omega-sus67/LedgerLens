# Role-Based Entitlement — Decisions

What Task 4 built, why each choice was made, and what it deliberately does not do.
Read this before changing `AccessRule`, `pipeline._visible_dims`, or the cache key on
`app.py:load_payload`.

Closes **Minimum Prototype Expectation row 7** — *"One role-based security or
entitlement scenario"* — the last uncovered row on that list.

Companion docs: [`contracts_decisions.md`](contracts_decisions.md) (where `AccessRule`
came from), [`persona_decisions.md`](persona_decisions.md) (the persona/payload
boundary this task extends). The implementation plan is
[`taskflow/roles_tasks.md`](../taskflow/roles_tasks.md).

---

## 1. What it does, in one paragraph

`mrr_renewals` declares one access rule: policy `fin.rail_detail` hides the
`payment_rail` dimension from the `growth` role, because payment-rail revenue splits
are finance-restricted. When a `growth` reader opens the card, `payment_rail` is
removed from the dimension list handed to `anomaly.drill()`. They get a real diagnosis
at a shallower cut — and a banner naming the policy, the dimension and the reason, so
the shallower answer reads as governance rather than as a broken engine.

## 2. The vocabulary

| Term | Meaning here |
|---|---|
| **Entitlement** | Which *cuts* (dimension slices) of a KPI a role may see. |
| **Row-level security** | Which *rows* a role may see. **Out of scope** — see §7. |
| **`AccessRule`** | `(policy_id, role, hidden_dims, reason)` on a `KpiContract`. |
| **Fail-open** | A role with no matching rule is unrestricted. |
| **Focal cohort** | The deepest, highest-contribution node from `drill()`. The headline number is its number. |
| **Payload boundary** | `diagnose()` → `NarrationPayload` → `narrate()` → card. Role sits **above** it; persona sits **below**. |
| **Redaction** | A record that a dimension was withheld: `(dim, policy_id, reason)`. |

## 3. The measurement that shaped every decision

Taken before any code was written, against the live store:

| | `analyst` (4 dims) | `growth` (3 dims) |
|---|---|---|
| focal cohort | `DACH · Enterprise · sepa` | `DACH · Enterprise · A` |
| headline | **−85.2%, −$416,144** | **−34.6%, −$207,545** |
| nodes naming `payment_rail` | 1 | 0 |
| ranked order | `deploy_sepa_v214`, `deploy_dunning_v3`, `deploy_billing_ui_v9`, `flag_sepa_retry_beta` | **identical** |
| top score | 0.700 | **0.627** |
| rejected decoy | `campaign_dach_cut` | `campaign_dach_cut` |
| clears `SCORE_FLOOR` (0.45) | yes | **yes** |

Three consequences, each of which became a decision or a test:

1. **The headline number changes for `growth`.** Correct — a shallower cut of the same
   anomaly — but it looks like a bug without the banner. Hence D3/D5.
2. **Scores move; order does not.** `hypothesis.rank()` scores against the *focal*
   cohort, and the focal moved. Hence D4 and the corrected test docstring.
3. **Growth still clears the score floor**, so entitlement does not accidentally trip
   the abstention path. Task 4 and Task 7 stay independent — asserted, not assumed.

## 4. Decisions

**D1 — Enforce at `drill()`, nowhere else.**
Entitlement is subtraction from one list: the `dims` argument to `anomaly.drill()`.
`hypothesis`, `controls` and `narrate` remain unaware that roles exist. One chokepoint
means no second place for the policy to be forgotten. The cost is that entitlement is
only as strong as the dimension list — see D7.

**D2 — `Redaction` is a frozen Pydantic model, not a `tuple[str, str, str]`.**
The original sketch used a bare 3-tuple. Every cross-module payload in this project is
a Pydantic model, for the reason `contracts.py`'s own docstring gives: a mistyped field
fails at import, and therefore in CI, rather than silently on stage. `r.policy_id` also
survives a field reorder in a way `r[1]` does not.

**D3 — A redaction is NOT an `EvidenceStep`.**
`EvidenceStep.query_id` is required, and there is no query behind a policy decision.
Faking one with `query_id=""` would put a claim with no provenance into the evidence
chain — precisely what this product's pitch forbids. `redactions` is its own field on
`NarrationPayload` and `DiagnosisCard`. This mirrors the carve-out Task 6 grants
telemetry: latency and policy are both facts about the *process*, not about the data,
and neither carries a `query_id` because there is no query behind either.

**D4 — Do not count the hidden slices.**
The tempting copy is *"2 deeper slices redacted by policy `fin.rail_detail`"*.
Producing that count means running the **unrestricted** drill — computing the exact
answer this reader is not entitled to, inside the process rendering their page. **A
redaction notice that must first compute the secret is not a redaction.** The line
names the dimension, the policy id and the reason; all three are free, all three come
off the `AccessRule`. (For the record the true count was 1, not 2 — the guessed number
was also wrong, which is its own argument.)

**D5 — `role=None` means unrestricted, and is the default.**
Every existing call site is byte-identical. `role="analyst"` also resolves to the full
`DRILL_DIMS` (fail-open, no rule matches), so the default card is unchanged — which is
what keeps `tests/test_app.py`'s `scores[0] == "0.700"` green.
`test_no_role_is_byte_identical_to_the_analyst_role` asserts it.

**D6 — Role is derived from the persona.**
`Persona.role` already existed and `tests/test_personas.py:39` already asserted that
`growth`'s role joins the contract's `AccessRule`. Threading `who.role` is the smallest
correct change and makes entitlement *in force* rather than a switch someone flips for
the demo. The alternative — a separate "View as role" control — was rejected: it reads
as a toggle rather than as policy.

**The consequence, stated plainly:** the line *"same evidence, four audiences,
identical query ids"* is **no longer true for `growth`**, who now gets a genuinely
different, shallower payload. It remains true for `analyst`, `cfo` and `oncall`.
`tests/test_narrate_personas.py` still passes, because it renders four personas from
one role-free payload — which is still the meaningful invariant, now stated precisely:
*at a fixed entitlement, prose differs and evidence does not.* **The demo script must
say this out loud**; see §6.

**D7 — Manual cohort selection is not entitlement-checked. Documented, not fixed.**
`app.py`'s manual-window path builds a cohort dict directly
(`{"region": [...], "payment_rail": ["sepa"]}`), bypassing `drill()` and therefore
bypassing D1's chokepoint. That path is reachable only for `status="sparse_history"`
KPIs — today only `payment_success_rate`, which declares **no** `AccessRule` — so there
is no live leak. It is still a hole in the shape of the feature. Closing it means
validating the cohort dict against `hidden_dims_for(role)` at the `diagnose()` entry,
which is ~10 lines and belongs with row-level security in the next phase. Named in the
roadmap rather than quietly omitted.

**D8 — Redactions are read off the contract, never inferred from the dim list.**
Populated by matching `contract.access` on the role, so `policy_id` and `reason` are
the declared strings. Diffing "what's missing from `DRILL_DIMS`" would produce a
redaction with no policy behind it — an unattributable refusal, which is the thing this
feature exists to avoid. `test_the_redaction_line_is_not_hardcoded_prose` asserts the
reason string is the contract's, so retyping it into `narrate.py` breaks the build.

**D9 — The engine uses the LENIENT contract lookup.**
`contracts.get()` raises on an ungoverned KPI; `contracts.CONTRACTS.get()` returns
`None`. `contracts.py:398` splits these deliberately — the UI should refuse to render
an ungoverned KPI, but *"detection must not crash because metadata is missing"*. The
original sketch called the strict one from inside `diagnose()`, inverting that.
`pipeline._contract_for_engine()` is the lenient path, matching `contracts.thresholds()`.

**D10 — The cache key is fixed once, here.**
`load_payload` now keys on `(metric, as_of, cohort, window, role)`. Persona stays out
of the key because it lives below the payload boundary. Task 7's `drop_sources` and
Task 5's feedback are the same shape and belong in this signature, not in three
separate patches. This is the debt [`persona_decisions.md`](persona_decisions.md) §10
left open.

## 5. What was built

| File | Change |
|---|---|
| `ledgerlens/models.py` | `Redaction` model; `DiagnosisCard.redactions: list[Redaction] = []`. |
| `ledgerlens/pipeline.py` | `_contract_for_engine`, `_visible_dims`, `_redactions_for`; `diagnose(role=)`; `run(role=, persona=)`. |
| `ledgerlens/narrate.py` | `NarrationPayload.redactions`; `_redaction_sentence()`; both card branches carry and state it. |
| `app.py` | `role_key` in the cache key; `who.role` at the call site; 🔒 banner beside the headline metrics. |
| `tests/test_entitlement.py` | 13 tests — the task's assertions. |
| `tests/test_app.py` | 3 tests — UI redaction, no false banner, cache correctness. |

**Test count: 184 → 200.** Updated in `README.md` at every commit rather than once at
the end, so no commit on this branch is red — `tests/test_docs.py` asserts the count,
and it fires on every task that adds tests. (A small friction the plan underestimated;
noted here so the next task expects it.)

## 6. What this does to the demo

The video's beat 5 — *"same evidence, four audiences; the query ids are identical"* —
must gain one sentence when the persona flips to Growth:

> "Growth is entitled to less. They lose the payment-rail cut, so their headline is
> $208k, not $416k — and the card says which policy did that and why. Same engine,
> same ranking, a different depth of the same truth."

Beat 7 (entitlement) then becomes the payoff of beat 5 rather than a separate scene.
Two details worth showing:

- The candidate **ranking is identical** — `deploy_sepa_v214` still wins, the campaign
  decoy is still rejected. Only the depth changed.
- Growth's negative control adapts to their entitled cohort: the decoy dies against
  `DACH · Mid|SMB · A` rather than `DACH · Mid|SMB · sepa`. The rejection still works
  at a cut they are allowed to see.

## 7. What this deliberately is not

- **Not row-level security.** We hide the `payment_rail` *breakdown*; sepa revenue is
  still inside the totals a growth reader sees. `AccessRule`'s docstring has said so
  since Task 1, and that remains the honest scope.
- **Not measure-level.** A role either sees a KPI or does not; there is no "sees the
  count but not the dollars".
- **Not enforced on manual cohort selection** — D7.
- **Not authentication.** The role comes from the persona selector, not from a login.
  This is a prototype of the *policy* layer, not of identity.

Each of these is a named line in the business proposal's roadmap. A gap we can point at
beats a gap a judge finds.
