# Documentation

Start with [**`how_it_works.md`**](how_it_works.md) if the vocabulary is new — it
explains the whole system from zero, assuming no analytics background. Everything else
here assumes it.

The [root `README.md`](../README.md) is the canonical description of what the system
does and the honest scope of its claims.

## Decision records

One per subsystem. Each says what was built, what was deliberately *not* built, and the
reasoning behind every choice a future reader might otherwise undo. Read the relevant
one before changing the code it covers.

| Doc | Covers |
|---|---|
| [`contracts_decisions.md`](contracts_decisions.md) | the KPI semantic contract — definitions, lineage, freshness, thresholds |
| [`persona_decisions.md`](persona_decisions.md) | four personas from one computation, and the `Action` chain |
| [`sparse_kpi_decisions.md`](sparse_kpi_decisions.md) | the newly-launched KPI that declines to auto-detect, and ratio aggregation |
| [`roles_decisions.md`](roles_decisions.md) | role-based entitlement, and why a redaction is not an `EvidenceStep` |
| [`telemetry_decisions.md`](telemetry_decisions.md) | latency, query accounting, and why "queries" is three numbers |
| [`abstention_decisions.md`](abstention_decisions.md) | the reachable path to *"nothing connected explains this"* |
| [`ai_decisions.md`](ai_decisions.md) | **the LLM investigator lane** — the provider seam, the validation gate, the numbers guard |
| [`learning_decisions.md`](learning_decisions.md) | the analyst feedback loop — a Beta–Bernoulli prior you can delete |

## Background

- [`design/IMPLEMENTATION_SPEC.md`](design/IMPLEMENTATION_SPEC.md) — the build contract
  the prototype was written against. `# SPEC-GAP:` comments in the source mark every
  deliberate deviation, each with its reason.
- [`design/businessintelligence-ai-redesign.md`](design/businessintelligence-ai-redesign.md)
  — the architecture rationale: why a change ledger and a set intersection rather than a
  graph database, a vector store and an agent framework.

## History

[`taskflow/`](taskflow/) holds the implementation plans each task was built from, kept
rather than deleted because several record errors that were only caught *during*
implementation — the corrected reasoning lives in the decision records above, and the
plans show what the correction was against.
