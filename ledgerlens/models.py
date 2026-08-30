"""All cross-module data contracts, plus the cohort algebra they rest on.

A Cohort is a conjunction across keys and a disjunction within a key:
    {"region": ["DACH"], "segment": ["Enterprise"]}
        -> region IN ('DACH') AND segment IN ('Enterprise')
An absent key is unconstrained (matches every value of that dimension).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

Cohort = dict[str, list[str]]


# ---------------------------------------------------------------- cohort algebra


def canonical_cohort_key(c: Cohort) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Order-invariant hashable identity for a cohort. Used for cache keys and ids."""
    return tuple(sorted((k, tuple(sorted(v))) for k, v in c.items() if v is not None))


def cohort_is_empty(c: Cohort) -> bool:
    """True when some key is constrained to the empty set (selects no rows)."""
    return any(len(v) == 0 for v in c.values())


def cohort_predicate(c: Cohort) -> str:
    """Render a cohort as a SQL WHERE fragment. Empty cohort -> 'TRUE'.

    Values are inlined rather than bound. They are safe because every cohort is
    validated against dim_registry (`validate_cohort`) before reaching SQL --
    cohort values are a closed set drawn from the dimension universe, never user
    text. Inlining also makes each cohort's query_id distinct, which is what the
    provenance registry needs.
    """
    if cohort_is_empty(c):
        return "FALSE"
    if not c:
        return "TRUE"
    parts = []
    for dim in sorted(c):
        values = ", ".join(f"'{v}'" for v in sorted(c[dim]))
        parts.append(f"{dim} IN ({values})")
    return " AND ".join(parts)


def cohort_intersect(a: Cohort, b: Cohort) -> Cohort | None:
    """Per-key set intersection. None when any shared key intersects to empty.

    Keys present in only one operand are carried through unchanged: an absent key
    is unconstrained, so intersecting it with a constraint yields the constraint.
    """
    out: Cohort = {}
    for dim in set(a) | set(b):
        if dim in a and dim in b:
            shared = sorted(set(a[dim]) & set(b[dim]))
            if not shared:
                return None
            out[dim] = shared
        else:
            out[dim] = sorted(a.get(dim) or b.get(dim) or [])
    return out


def cohort_complement(base: Cohort, dim: str, universe: list[str]) -> Cohort:
    """`base` with `dim` flipped to (universe - base[dim]). Used to build controls."""
    if dim not in base:
        raise ValueError(f"cannot complement unconstrained dimension {dim!r}")
    out = {k: list(v) for k, v in base.items()}
    out[dim] = sorted(set(universe) - set(base[dim]))
    return out


def validate_cohort(c: Cohort, registry: dict[str, list[str]]) -> None:
    """Raise if any dimension or value falls outside the known universe."""
    for dim, values in c.items():
        if dim not in registry:
            raise ValueError(f"unknown dimension {dim!r}")
        unknown = set(values) - set(registry[dim])
        if unknown:
            raise ValueError(f"unknown values for {dim!r}: {sorted(unknown)}")


# Reading order for humans: geography, then who, then how they pay, then what.
# Alphabetical order would render the focal cohort as "sepa · DACH · Enterprise".
DIM_ORDER = ["region", "segment", "payment_rail", "product"]


def cohort_label(c: Cohort) -> str:
    """Human-readable one-liner for the UI and narration."""
    if not c:
        return "all business"
    dims = [d for d in DIM_ORDER if d in c] + [d for d in sorted(c) if d not in DIM_ORDER]
    return " · ".join("|".join(sorted(c[d])) for d in dims)


def stable_id(prefix: str, *parts: object) -> str:
    payload = json.dumps([str(p) for p in parts], sort_keys=True)
    return f"{prefix}_{hashlib.sha1(payload.encode()).hexdigest()[:10]}"


# ---------------------------------------------------------------- core models


class Window(BaseModel):
    model_config = ConfigDict(frozen=True)
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


class Anomaly(BaseModel):
    model_config = ConfigDict(frozen=True)
    anomaly_id: str
    metric: str
    cohort: Cohort
    window: Window
    onset: date
    actual: float
    expected: float
    delta_abs: float
    delta_pct: float
    residual_z: float
    contribution: float  # share of PARENT delta explained; 1.0 at root
    depth: int
    parent_id: str | None
    query_id: str
    rows_per_day: float = 0.0
    # SPEC-GAP: spec 7.2 requires recording BH survival per node but spec 3's model
    # has no field for it. Labels only -- never gates.
    bh_survived: bool = True
    bh_p: float = 1.0


class ChangeEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_id: str
    event_type: Literal[
        "deploy",
        "feature_flag",
        "price_change",
        "campaign",
        "policy_change",
        "vendor_incident",
        "external",
    ]
    ts_start: datetime
    ts_end: datetime | None
    source: str
    blast_radius: Cohort
    description: str
    evidence_refs: list[str]
    extraction: Literal["deterministic", "llm"] = "deterministic"
    confidence: float = 1.0


class SymptomCluster(BaseModel):
    model_config = ConfigDict(frozen=True)
    cluster_id: str
    key: str
    cohort: Cohort
    first_seen: date
    volume: int
    baseline_volume: float
    lift: float
    sample_refs: list[str]
    query_id: str = ""


class ControlResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    cohort: Cohort
    metric: str = "mrr_renewals"
    prediction: Literal["should_be_flat", "should_also_drop"]
    observed_delta_pct: float
    passed: bool
    decisive: bool = False
    query_id: str
    rule: str = ""


class ComponentScores(BaseModel):
    model_config = ConfigDict(frozen=True)
    T: float
    C: float
    D: float
    N: float
    P: float

    def total(self, w: dict[str, float]) -> float:
        return w["T"] * self.T + w["C"] * self.C + w["D"] * self.D + w["N"] * self.N + w["P"] * self.P


class EffectEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)
    method: Literal["did_ratio", "did_regression", "observed_shortfall"]
    counterfactual: float
    actual: float
    impact_abs: float
    ci_low: float
    ci_high: float
    control_cohort: Cohort
    pre_fit_quality: float
    query_id: str


class Hypothesis(BaseModel):
    model_config = ConfigDict(frozen=True)
    hypothesis_id: str
    anomaly_id: str
    event: ChangeEvent
    scores: ComponentScores
    total: float
    controls: list[ControlResult]
    symptoms: list[SymptomCluster]
    effect: EffectEstimate | None = None
    rejection_reason: str | None = None
    query_ids: list[str] = []


class DiscriminatingTest(BaseModel):
    model_config = ConfigDict(frozen=True)
    h1_id: str
    h2_id: str
    disagreement: str
    resolvable_now: bool
    sql: str | None = None
    result: str | None = None
    proposed_experiment: str | None = None
    owner_hint: str = ""


class ProposedTest(BaseModel):
    model_config = ConfigDict(frozen=True)
    template: Literal[
        "compare_cohort", "check_metric_in_cohort", "check_symptom_lift", "check_temporal_order"
    ]
    params: dict[str, str | list[str]]
    rationale: str
    result: ControlResult | None = None
    provenance: Literal["llm"] = "llm"


class UnverifiedHypothesis(BaseModel):
    model_config = ConfigDict(frozen=True)
    description: str
    needed_source: str
    would_test: str


class EvidenceStep(BaseModel):
    model_config = ConfigDict(frozen=True)
    claim: str
    query_id: str
    observed: str


class Redaction(BaseModel):
    """A dimension withheld from this reader by policy.

    Deliberately NOT an EvidenceStep: that model requires a `query_id`, and there is
    no query behind a policy decision. Putting a provenance-free claim into the
    evidence chain would break the one invariant this product rests on.

    Carries the policy id and reason so the card can ATTRIBUTE the refusal rather than
    merely perform it. Both strings are copied off the contract's `AccessRule`, never
    retyped into narration -- see docs/roles_decisions.md D8.
    """

    model_config = ConfigDict(frozen=True)
    dim: str
    policy_id: str
    reason: str


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


class DiagnosisCard(BaseModel):
    model_config = ConfigDict(frozen=True)
    headline: str
    summary: str
    causal_chain: list[EvidenceStep]
    effect: EffectEstimate | None
    ranked: list[Hypothesis]
    rejected: list[Hypothesis]
    open_question: DiscriminatingTest | None
    actions: list[Action]
    proposed_tests: list[ProposedTest] = []
    unverified: list[UnverifiedHypothesis] = []
    generated_by: Literal["llm", "template"] = "template"
    # context the UI needs that isn't a hypothesis
    focal: Anomaly | None = None
    root: Anomaly | None = None
    nodes: list[Anomaly] = []
    seasonal_pct: float = 0.0
    seasonal_query_id: str = ""
    no_confident_cause: bool = False
    # What policy withheld from this reader. Defaulted, so every existing
    # construction site stays valid and an unrestricted card is simply empty.
    redactions: list[Redaction] = []

    @staticmethod
    def no_anomaly(metric: str, as_of: date) -> "DiagnosisCard":
        return DiagnosisCard(
            headline=f"No anomaly detected in {metric} as of {as_of}.",
            summary=(
                f"{metric} stayed within its expected band through {as_of}. "
                "Detection is advisory -- point the pipeline at a specific slice "
                "from the sidebar if you suspect something it did not surface."
            ),
            causal_chain=[],
            effect=None,
            ranked=[],
            rejected=[],
            open_question=None,
            actions=[],
        )


class ExtractedSignal(BaseModel):
    """Output of the (unbuilt) LLM normalizer lane. Declared for schema completeness."""

    model_config = ConfigDict(frozen=True)
    is_change_event: bool
    event: ChangeEvent | None = None
    entities: list[str] = []
    signal: str | None = None
    suggested_link: str | None = None
    confidence: float = 0.7
