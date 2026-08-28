"""LedgerLens analyst UI.

Deliberately plain. The content is the impressive part: every number on this page
comes from a registered query, and every hypothesis card shows the checks that were
run against it -- including the ones that killed it.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

import config
from ledgerlens import contracts, pipeline
from ledgerlens.models import cohort_label

st.set_page_config(page_title="LedgerLens", page_icon="🔎", layout="wide")


@st.cache_resource(show_spinner="Running diagnosis...")
def load(metric: str, as_of_iso: str):
    from datetime import date

    store = pipeline.get_store()
    card = pipeline.run(metric, date.fromisoformat(as_of_iso), store=store)
    return store, card


def money(x: float) -> str:
    return f"{'-' if x < 0 else ''}${abs(x):,.0f}"


# ------------------------------------------------------------------- sidebar

st.sidebar.title("🔎 LedgerLens")
st.sidebar.caption("Anomaly ∩ change ledger, verified by negative controls.")

metric = st.sidebar.selectbox("Metric", config.METRICS, index=0)
as_of = st.sidebar.date_input("As of", pipeline.DEFAULT_AS_OF)

st.sidebar.subheader("Scoring weights")
st.sidebar.caption("A product decision, not a hidden hyperparameter.")
st.sidebar.table(
    pd.DataFrame(
        {
            "component": ["T temporal", "C cohort match", "D dose-response", "N controls", "P prior"],
            "weight": list(config.SCORE_WEIGHTS.values()),
        }
    ).set_index("component")
)
# Read off the contract, not off config: these are the values in force FOR THIS KPI,
# and they are the same object scan_for_onset() was handed. SCORE_FLOOR and SEED stay
# global -- they are pipeline parameters, not per-KPI alerting policy.
th = contracts.thresholds(metric)
st.sidebar.subheader("Thresholds")
st.sidebar.caption(f"In force for `{metric}`, from its contract.")
st.sidebar.write(
    {
        "MAD z": th.mad_z,
        "min consecutive days": th.min_consecutive,
        "min material drop %": th.min_abs_delta_pct,
        "warmup days": th.warmup_days,
        "score floor": config.SCORE_FLOOR,
        "seed": config.SEED,
    }
)

store, card = load(metric, as_of.isoformat())

# ------------------------------------------------------------- 1. the anomaly

st.title(card.headline)

if card.focal is None:
    st.success(card.summary)
    st.stop()

root, focal = card.root, card.focal
unexplained = 100 * ((1 + root.delta_pct / 100) / (1 + card.seasonal_pct / 100) - 1)

c1, c2, c3, c4 = st.columns(4)
c1.metric(f"{metric} (aggregate)", f"{root.delta_pct:.1f}%", delta=money(root.delta_abs))
c2.metric("Focal cohort", f"{focal.delta_pct:.1f}%", delta=money(focal.delta_abs))
c3.metric("Share of the drop", f"{100 * focal.contribution:.0f}%", delta="of parent shortfall")
c4.metric("Robust z", f"{focal.residual_z:.1f}", delta=f"threshold {-th.mad_z}")

st.markdown(
    f"### Expected **{card.seasonal_pct:.1f}%** (August seasonality). "
    f"Unexplained: **{unexplained:.1f}%** (z = {root.residual_z:.1f})."
)
st.caption(
    f"Focal cohort: **{cohort_label(focal.cohort)}** · window {focal.window.start} → "
    f"{focal.window.end} · seasonality measured from the same cohort a year earlier "
    f"[{card.seasonal_query_id}]"
)

# ------------------------------------------------------------ 1b. the contract

# `contracts.get` is the STRICT lookup: an ungoverned KPI raises here rather than
# rendering an empty box. The engine's lookup is deliberately lenient -- detection
# degrades to global defaults -- so this expander is where a governance gap becomes
# visible instead of silent.
contract = contracts.get(metric)

with st.expander("📜 Contract — what this KPI means, and who may see which cuts of it"):
    st.markdown(
        f"**{contract.name}** · {contract.unit} · owner **{contract.owner}** · "
        f"status `{contract.status}`"
    )
    st.write(contract.definition)

    st.markdown("**Calculation** — the aggregation the engine actually issues.")
    st.code(contract.calculation_sql, language="sql")

    left, right = st.columns(2)
    left.markdown("**Known drivers**")
    left.markdown("\n".join(f"- {d}" for d in contract.drivers))

    right.markdown("**Alerting thresholds in force**")
    right.table(
        pd.DataFrame(
            [
                {"rule": "robust z past", "value": f"-{contract.thresholds.mad_z}"},
                {"rule": "for at least", "value": f"{contract.thresholds.min_consecutive} days"},
                {"rule": "and a drop of at least", "value": f"{contract.thresholds.min_abs_delta_pct}%"},
                {"rule": "after a warmup of", "value": f"{contract.thresholds.warmup_days} days"},
                {"rule": "direction (declared)", "value": contract.thresholds.direction},
            ]
        ).set_index("rule")
    )

    if contract.anticipated_event_types:
        st.caption(
            "🔌 We would also weigh "
            + ", ".join(f"`{t}`" for t in contract.anticipated_event_types)
            + " — no source is connected for these, so they can never appear as a "
            "candidate. Named rather than silently missing."
        )

    st.markdown("**Lineage & freshness** — declared cadence beside what is actually there.")
    st.caption(
        f"Measured as of **{as_of}**, not the wall clock: this page is a time-travel "
        f"replay, and the generated ledger runs past the as-of date."
    )
    fresh = {f.source_system: f for f in contracts.freshness(store, metric, as_of)}
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "source": s.source_system,
                    "kind": s.kind,
                    "artifact": s.artifact,
                    "table": s.table,
                    "grain": s.grain,
                    "declared cadence": s.refresh_cadence,
                    "last seen": str(fresh[s.source_system].last_seen or "—"),
                    "lag (days)": fresh[s.source_system].lag_days,
                }
                for s in contract.lineage
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    st.caption(
        "Freshness queries: "
        + " · ".join(f"`{f.query_id}`" for f in fresh.values())
        + " — logged and replayable like every other number on this page."
    )

    st.markdown("**Access policy**")
    if contract.access:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "policy": r.policy_id,
                        "role": r.role,
                        "hidden dimensions": ", ".join(r.hidden_dims),
                        "reason": r.reason,
                    }
                    for r in contract.access
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "Dimension-level only — this governs which *cuts* a role sees, not which "
            "rows. Roles with no rule are unrestricted."
        )
    else:
        st.caption("No dimension restrictions on this KPI.")

st.divider()

# --------------------------------------------------------------- 2. attribution

st.subheader("Attribution")
st.caption(
    "Top-down: test the aggregate, then expand only where the parent is anomalous. "
    "Bounds the number of tests to the anomalous path instead of the full cross-product."
)

rows = []
for n in card.nodes:
    rows.append(
        {
            "depth": n.depth,
            "cohort": cohort_label(n.cohort),
            "delta %": round(n.delta_pct, 2),
            "shortfall": round(n.delta_abs),
            "contribution": round(n.contribution, 3),
            "z": round(n.residual_z, 1),
            "rows/day": n.rows_per_day,
            "BH": "✓" if n.bh_survived else "·",
            "focal": "◀ focal" if n.anomaly_id == focal.anomaly_id else "",
        }
    )
st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

st.divider()

# --------------------------------------------------------------- 3. hypotheses

st.subheader("Hypotheses")
st.caption(
    f"Candidates are recorded changes whose blast radius intersects the focal cohort "
    f"and which started within {config.LOOKBACK_DAYS} days before onset. "
    f"Scored on five auditable components; every one is a query you can open."
)


def render_hypothesis(h, rank: int | None, rejected: bool) -> None:
    with st.container(border=True):
        if rejected:
            st.error(f"**REJECTED** — {h.rejection_reason}", icon="🚫")
            title = f"~~{h.event.event_id}~~"
        else:
            title = f"**#{rank} · {h.event.event_id}**"

        left, right = st.columns([4, 1])
        left.markdown(f"{title} — {h.event.description}")
        left.caption(
            f"{h.event.event_type} · {h.event.source} · started "
            f"{h.event.ts_start:%Y-%m-%d %H:%M} · blast radius "
            f"**{cohort_label(h.event.blast_radius) or 'unconstrained'}**"
        )
        badge = "Recorded" if h.event.extraction == "deterministic" else "Inferred — verify"
        right.metric("score", f"{h.total:.3f}")
        right.caption(f"🏷️ {badge}")

        cols = st.columns(5)
        labels = {
            "T": "Temporal",
            "C": "Cohort match",
            "D": "Dose–response",
            "N": "Controls",
            "P": "Prior",
        }
        for col, key in zip(cols, ["T", "C", "D", "N", "P"]):
            value = getattr(h.scores, key)
            col.caption(f"**{key}** {labels[key]} · w={config.SCORE_WEIGHTS[key]}")
            col.progress(min(max(value, 0.0), 1.0), text=f"{value:.2f}")

        if h.controls:
            frame = pd.DataFrame(
                [
                    {
                        "": "✗" if not c.passed else "✓",
                        "control": c.name,
                        "rule": c.rule,
                        "prediction": c.prediction.replace("_", " "),
                        "observed %": round(c.observed_delta_pct, 2),
                        "decisive": "◀ killed it" if c.decisive else "",
                    }
                    for c in h.controls
                ]
            )

            def highlight(row):
                if row["decisive"]:
                    return ["background-color: #f8d7da; color: #58151c"] * len(row)
                if row[""] == "✗":
                    return ["background-color: #fff3cd"] * len(row)
                return [""] * len(row)

            st.dataframe(
                frame.style.apply(highlight, axis=1), width="stretch", hide_index=True
            )

        if h.symptoms:
            for cluster in h.symptoms:
                st.markdown(
                    f"🎫 **{cluster.volume}** tickets keyed `{cluster.key}` in "
                    f"{cohort_label(cluster.cohort)} from {cluster.first_seen} — "
                    f"**{cluster.lift:.0f}×** baseline. "
                    f"Corroborating evidence only; deliberately not scored."
                )

        with st.expander("🔍 show the queries behind this card"):
            for qid in dict.fromkeys([c.query_id for c in h.controls] + h.query_ids):
                row = store.query_row(qid)
                if row is None:
                    continue
                st.caption(f"`{qid}` — {row['label']}")
                st.code(row["sql"], language="sql")
                st.text(row["result_preview"])


for i, h in enumerate(card.ranked, 1):
    render_hypothesis(h, i, rejected=False)
for h in card.rejected:
    render_hypothesis(h, None, rejected=True)

st.divider()

# ---------------------------------------------------------------- 4. diagnosis

st.subheader("Diagnosis")
st.info(card.summary)

st.markdown("**Evidence chain** — every claim carries the query that produced it.")
for i, step in enumerate(card.causal_chain, 1):
    st.markdown(f"**{i}.** {step.claim}")
    st.caption(f"→ {step.observed}  ·  `{step.query_id}`")
    row = store.query_row(step.query_id)
    if row is not None:
        with st.expander("🔍 show query"):
            st.code(row["sql"], language="sql")
            st.text(row["result_preview"])

st.markdown("**Recommended actions**")
for a in card.actions:
    st.markdown(f"**[{a.priority}] {a.owner}** — {a.action}")
    st.caption(f"basis: {a.basis}")

st.divider()
st.caption(
    f"Generated by the {card.generated_by} narrator. This system ranks evidence and "
    f"reports the checks behind each claim; it does not prove causation. "
    f"Effect is reported as an observed shortfall against a deseasonalized baseline, "
    f"not as a causal impact estimate."
)
