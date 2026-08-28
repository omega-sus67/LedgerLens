"""Governed KPI definitions.

A KpiContract is what the business has agreed a metric MEANS: how it is computed,
what is known to move it, when it is worth alerting on, where its numbers came from,
and who may see which cuts of it.

It is executable, not documentation. The anomaly engine reads its thresholds, the UI
renders its calculation SQL, and source freshness is measured against its declared
lineage. A contract that drifts from the engine is a test failure, not a surprise on
stage.

Python rather than YAML: a mistyped dimension fails at import (and therefore in CI)
instead of silently at demo time, and every other cross-module payload in this
project is already a Pydantic model.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, get_args

from pydantic import BaseModel, ConfigDict, field_validator

import config
from ledgerlens.models import ChangeEvent

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, runtime never needs it
    from ledgerlens.store import Store

# The single source of truth for what an event type may be. Read off the model
# rather than retyped, so adding a type in one place cannot silently diverge here.
EVENT_TYPES: frozenset[str] = frozenset(
    get_args(ChangeEvent.model_fields["event_type"].annotation)
)


class LineageStep(BaseModel):
    """One upstream system feeding this KPI, or the context used to explain it.

    `kind` separates the metric's own data path from the context that explains it,
    because the freshness panel needs to say different things about them: a stale
    metric feed invalidates the number, a stale deploy feed only means a candidate
    cause might be missing from the ledger.
    """

    model_config = ConfigDict(frozen=True)

    source_system: str
    artifact: str
    table: str
    grain: str
    refresh_cadence: str
    kind: str = "metric"  # "metric" | "context" | "symptom"


class SourceFreshness(BaseModel):
    """What a lineage step DECLARED, beside what the data actually shows.

    A contract can promise "daily batch, 02:00 UTC" and be wrong; this is the
    measurement that catches it. `last_seen`/`lag_days` are None when a source has no
    rows at all -- render that as "no data", never as a lag of zero.
    """

    model_config = ConfigDict(frozen=True)

    source_system: str
    kind: str
    declared_cadence: str
    last_seen: date | None
    lag_days: int | None
    query_id: str


class Thresholds(BaseModel):
    """Alerting rules for one KPI.

    Every default is exactly the global constant, so an unset field can never change
    detection behaviour. That invariant is what makes wiring contracts into the
    engine a pure refactor; per-metric divergence is a later, deliberate act (a rate
    metric bounded near 98% needs a very different relative gate from a dollar sum).
    """

    model_config = ConfigDict(frozen=True)

    mad_z: float = config.MAD_Z_THRESHOLD
    min_consecutive: int = config.MIN_CONSECUTIVE_PERIODS
    min_abs_delta_pct: float = config.MIN_ABS_DELTA_PCT
    warmup_days: int = config.DETECT_WARMUP_DAYS
    # DECLARED, NOT ENFORCED: scan_for_onset hardcodes the negative sign. v1 flags
    # drops only because the generator's quarter-end multiplier would make a
    # bidirectional detector fire at every quarter close; the fix is a
    # calendar-regressor baseline, not a threshold. Stated so the contract does not
    # imply a guarantee the engine does not make.
    direction: str = config.DIRECTION


class AccessRule(BaseModel):
    """A role that may not drill into certain dimensions of this KPI.

    Dimension-level only: this governs which CUTS a role sees, not which rows or
    which measures. Row-level security is a real production requirement and is
    deliberately out of scope. Roles with no rule are unrestricted -- fail-open,
    because the sensitive surface here is a named subset of dimensions rather than
    the metric itself.
    """

    model_config = ConfigDict(frozen=True)

    policy_id: str
    role: str
    hidden_dims: list[str]
    reason: str


class KpiContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    definition: str
    unit: str
    owner: str
    calculation_sql: str
    grain_dims: list[str]
    drivers: list[str]  # plain English, for the card
    # Split deliberately. `related` is what the ledger can actually show us today;
    # `anticipated` is a known driver we have no connector for. Naming the second
    # list is the honest-refusal move: a gap we can point at beats a silent one, and
    # the UI renders it as "we would also look for X -- no source connected".
    related_event_types: list[str]
    anticipated_event_types: list[str] = []
    lineage: list[LineageStep]
    thresholds: Thresholds = Thresholds()
    access: list[AccessRule] = []
    status: str = "active"  # "active" | "sparse_history"

    @field_validator("grain_dims")
    @classmethod
    def _known_dims(cls, v: list[str]) -> list[str]:
        unknown = set(v) - set(config.DIMENSIONS)
        if unknown:
            raise ValueError(f"unknown dimensions: {sorted(unknown)}")
        return v

    @field_validator("related_event_types", "anticipated_event_types")
    @classmethod
    def _known_event_types(cls, v: list[str]) -> list[str]:
        unknown = set(v) - EVENT_TYPES
        if unknown:
            raise ValueError(f"unknown event types: {sorted(unknown)}")
        return v

    @field_validator("access")
    @classmethod
    def _known_hidden_dims(cls, v: list[AccessRule]) -> list[AccessRule]:
        for rule in v:
            unknown = set(rule.hidden_dims) - set(config.DIMENSIONS)
            if unknown:
                raise ValueError(f"{rule.policy_id}: unknown dimensions {sorted(unknown)}")
        return v

    def hidden_dims_for(self, role: str) -> list[str]:
        out: set[str] = set()
        for rule in self.access:
            if rule.role == role:
                out.update(rule.hidden_dims)
        return sorted(out)

    def visible_drill_dims(self, role: str) -> list[str]:
        """DRILL_DIMS minus what policy hides from `role`. Task 2.5 calls this."""
        hidden = set(self.hidden_dims_for(role))
        return [d for d in config.DRILL_DIMS if d not in hidden]


# The context sources are shared: both KPIs are explained from the same ledger.
# Cadences differ by source ON PURPOSE -- that is the "heterogeneous sources with
# different grains and refresh cadences" the brief asks to see.
_CONTEXT_LINEAGE = [
    LineageStep(
        source_system="github",
        artifact="data/events_deploys.json",
        table="change_event",
        grain="one row per merged deploy",
        refresh_cadence="event-time webhook (seconds)",
        kind="context",
    ),
    LineageStep(
        source_system="launchdarkly",
        artifact="data/events_flags.json",
        table="change_event",
        grain="one row per flag state change",
        refresh_cadence="event-time webhook (seconds)",
        kind="context",
    ),
    LineageStep(
        source_system="calendar",
        artifact="data/events_campaigns.json",
        table="change_event",
        grain="one row per campaign flight",
        refresh_cadence="weekly planning export",
        kind="context",
    ),
    LineageStep(
        source_system="pricing_db",
        artifact="data/events_pricing.json",
        table="change_event",
        grain="one row per SKU x region price change",
        refresh_cadence="on change (SCD-2 diff)",
        kind="context",
    ),
]

_TICKET_LINEAGE = LineageStep(
    source_system="zendesk",
    artifact="data/tickets.json",
    table="ticket",
    grain="one row per ticket",
    refresh_cadence="hourly incremental",
    kind="symptom",
)


CONTRACTS: dict[str, KpiContract] = {
    "mrr_renewals": KpiContract(
        name="mrr_renewals",
        definition=(
            "Recurring revenue from subscription renewals that completed successfully "
            "on the day, summed across every slice of the business."
        ),
        unit="USD/day",
        owner="revenue operations",
        # The literal aggregation Store.series issues for an unconstrained cohort
        # (cohort_predicate({}) renders as TRUE and is elided here).
        calculation_sql=(
            "SELECT date, SUM(value) AS value FROM fact_metric "
            "WHERE metric_name = 'mrr_renewals' AND date BETWEEN $start AND $end "
            "GROUP BY date ORDER BY date"
        ),
        grain_dims=["region", "segment", "payment_rail", "product"],
        drivers=[
            "payment rail availability and gateway health",
            "billing and connector deploys",
            "dunning / retry policy",
            "price and packaging changes",
            "seasonality (August dip, quarter-end pull-forward)",
        ],
        related_event_types=["deploy", "feature_flag", "price_change"],
        # Gateway outages and dunning-policy changes are top-3 drivers of renewal
        # revenue and we have no feed for either. Declared, not pretended.
        anticipated_event_types=["vendor_incident", "policy_change"],
        lineage=[
            LineageStep(
                source_system="billing_db",
                artifact="data/metrics.parquet",
                table="fact_metric",
                grain="daily x region x segment x payment_rail x product",
                refresh_cadence="daily batch, 02:00 UTC",
                kind="metric",
            ),
            *_CONTEXT_LINEAGE,
            _TICKET_LINEAGE,
        ],
        access=[
            AccessRule(
                policy_id="fin.rail_detail",
                role="growth",
                hidden_dims=["payment_rail"],
                reason=(
                    "Payment-rail revenue splits are finance-restricted; growth sees "
                    "region and segment cuts only."
                ),
            )
        ],
    ),
    "new_logo_bookings": KpiContract(
        name="new_logo_bookings",
        definition=(
            "Committed first-year contract value from newly acquired logos, dated on "
            "contract signature."
        ),
        unit="USD/day",
        owner="growth marketing",
        calculation_sql=(
            "SELECT date, SUM(value) AS value FROM fact_metric "
            "WHERE metric_name = 'new_logo_bookings' AND date BETWEEN $start AND $end "
            "GROUP BY date ORDER BY date"
        ),
        grain_dims=["region", "segment", "payment_rail", "product"],
        drivers=[
            "marketing spend and campaign flighting",
            "price and packaging changes",
            "competitive and macro demand",
            "seasonality",
        ],
        related_event_types=["campaign", "price_change"],
        anticipated_event_types=["external", "policy_change"],
        lineage=[
            LineageStep(
                source_system="crm",
                artifact="data/metrics.parquet",
                table="fact_metric",
                grain="daily x region x segment x payment_rail x product",
                refresh_cadence="daily batch, 02:00 UTC",
                kind="metric",
            ),
            *_CONTEXT_LINEAGE,
        ],
    ),
}


def get(metric: str) -> KpiContract:
    """Strict lookup, for the UI. Raises when a KPI is ungoverned."""
    try:
        return CONTRACTS[metric]
    except KeyError:
        raise KeyError(
            f"no contract registered for {metric!r} -- refusing to present an "
            f"ungoverned KPI. Add one to ledgerlens/contracts.py."
        ) from None


def thresholds(metric: str) -> Thresholds:
    """Lenient lookup, for the engine. Falls back to the global defaults.

    Deliberately split from `get`: the UI should refuse to render a KPI nobody has
    defined, but detection must not crash because metadata is missing. The engine
    degrades to the documented global behaviour; the UI is where the governance gap
    becomes visible.
    """
    contract = CONTRACTS.get(metric)
    return contract.thresholds if contract else Thresholds()


# ------------------------------------------------------------------- freshness

# One SQL shape per lineage kind. Written here rather than in the UI so the
# measurement is part of the contract module, testable without Streamlit.
#
# Every predicate is bounded by `as_of`, and that bound is load-bearing: the demo is
# a time-travel replay pinned at DEFAULT_AS_OF = 2026-08-17 while the generator
# writes through GEN_END = 2026-08-31. An unbounded max(date) reports data from two
# weeks in the future and renders a NEGATIVE lag on stage. Freshness is always
# relative to the as-of date, never to the wall clock.
#
# ts_start/created_at are TIMESTAMPs and as_of is a DATE; comparing them directly
# would truncate to midnight and drop everything recorded during the as-of day
# itself, so both are cast to DATE first.
_FRESHNESS_SQL = {
    "metric": (
        "SELECT max(date) AS last_seen FROM fact_metric "
        "WHERE metric_name = $metric AND date <= $as_of"
    ),
    "context": (
        "SELECT max(ts_start) AS last_seen FROM change_event "
        "WHERE source = $source AND CAST(ts_start AS DATE) <= $as_of"
    ),
    "symptom": (
        "SELECT max(created_at) AS last_seen FROM ticket "
        "WHERE CAST(created_at AS DATE) <= $as_of"
    ),
}


def _as_date(value) -> date | None:
    """Normalise DuckDB's DATE / TIMESTAMP / NULL to a plain date."""
    if value is None:
        return None
    # pandas returns NaT for a NULL max() over a timestamp column, and NaT is not
    # None -- checking truthiness or `is None` alone silently yields a garbage lag.
    if value != value:  # NaN / NaT
        return None
    return value.date() if hasattr(value, "date") else value


def freshness(store: "Store", metric: str, as_of: date) -> list[SourceFreshness]:
    """Measured freshness for every lineage step of `metric`, as of `as_of`.

    Issued through `store.q()`, never `store.con.execute` -- these are numbers a user
    reads, so they carry a query_id and are replayable like every other number on the
    page. That is also why `store.max_date()` is not reused: it bypasses the registry
    AND takes no as-of bound.
    """
    contract = get(metric)
    out: list[SourceFreshness] = []
    for step in contract.lineage:
        sql = _FRESHNESS_SQL[step.kind]
        params: dict = {"as_of": as_of}
        if step.kind == "metric":
            params["metric"] = metric
        elif step.kind == "context":
            params["source"] = step.source_system

        df, query_id = store.q(sql, params, label=f"freshness: {step.source_system}")
        last_seen = _as_date(df["last_seen"].iloc[0]) if not df.empty else None
        out.append(
            SourceFreshness(
                source_system=step.source_system,
                kind=step.kind,
                declared_cadence=step.refresh_cadence,
                last_seen=last_seen,
                lag_days=(as_of - last_seen).days if last_seen else None,
                query_id=query_id,
            )
        )
    return out
