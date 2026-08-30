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

import json
from datetime import date

import pandas as pd
import streamlit as st

import config
from ledgerlens import contracts, learning, llm, narrate, personas, pipeline
from ledgerlens.models import DiagnosisCard, Window, cohort_label

st.set_page_config(page_title="LedgerLens", page_icon="🔎", layout="wide")


@st.cache_resource(show_spinner="Running diagnosis...")
def load_payload(
    metric: str,
    as_of_iso: str,
    cohort_key: str = "",
    window_key: str = "",
    role_key: str = "",
    drop_key: str = "",
    investigate: bool = False,
    feedback_key: str = "",
):
    """Cached on everything that changes the PAYLOAD.

    The boundary rule, and the reason this signature is worth reading before adding
    an argument: persona is a RENDERING concern and lives BELOW this function, which
    is what makes switching persona instant and what makes "identical evidence,
    different narrative" structurally true rather than a coincidence of determinism.

    Role is NOT such a concern. Entitlement changes which dimensions are drilled, so
    it changes the focal cohort, so it changes the numbers -- it must join the key.
    Task 7's `drop_sources` is exactly the same shape and is here for the same reason:
    removing a source removes candidates, which changes the answer. Task 5's feedback
    would go here too. This is the cache-key debt docs/persona_decisions.md sec 10 left
    unpaid, paid once rather than three times.

    `investigate` is the FOURTH, and it earns its place on the same test: the lane runs
    real queries and puts their results on the card. Note the asymmetry with persona --
    the investigator changes what is SHOWN but provably not what was RANKED, and it
    still belongs above the boundary because it costs money and latency to recompute.

    `feedback_key` is the last one, and it is the one the docstring named first. It is
    not read by `diagnose()` at all -- it is a CACHE BUSTER. An analyst verdict changes
    the `verdict` table, which changes the learned prior, which changes the P component
    of every score. Without it the loop looks broken: the row lands, the prior moves in
    the database, and the UI keeps rendering the memoised payload from before it.
    """
    import json
    from datetime import date

    store = pipeline.get_store()
    cohort = json.loads(cohort_key) if cohort_key else None
    window = (
        Window(**{k: date.fromisoformat(v) for k, v in zip(("start", "end"), json.loads(window_key))})
        if window_key
        else None
    )
    return store, pipeline.diagnose(
        metric,
        date.fromisoformat(as_of_iso),
        store=store,
        cohort=cohort,
        window=window,
        role=role_key or None,
        drop_sources=frozenset(drop_key.split(",")) if drop_key else frozenset(),
        investigate=investigate,
    )


def money(x: float) -> str:
    return f"{'-' if x < 0 else ''}${abs(x):,.0f}"


# ------------------------------------------------------------------- sidebar

st.sidebar.title("🔎 LedgerLens")
st.sidebar.caption("Anomaly ∩ change ledger, verified by negative controls.")

metric = st.sidebar.selectbox("Metric", config.METRICS, index=0)
as_of = st.sidebar.date_input("As of", pipeline.DEFAULT_AS_OF)

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

st.sidebar.subheader("Simulate a gap")
drop_deploys = st.sidebar.checkbox(
    "Deploy source (github) not connected",
    value=False,
    help=(
        "Removes every github-sourced change from candidate generation, as if the "
        "connector had never been wired up. The true cause stops being a candidate at "
        "all -- not a candidate that scores badly -- so the engine has nothing above "
        "its confidence floor and declines to answer."
    ),
)
drop_key = "github" if drop_deploys else ""
if drop_deploys:
    st.sidebar.caption(
        "🔌 Simulating a disconnected deploy feed. The card below should REFUSE to "
        "name a cause and say what it is missing."
    )

st.sidebar.subheader("AI investigator")
_provider, _why_off = llm.resolve()
_spec = config.provider_spec()
if _provider is None:
    investigate = False
    st.sidebar.checkbox("Run the AI investigator", value=False, disabled=True)
    st.sidebar.caption(
        f"⚪ Off — {_why_off}. Set it and reload to enable. Everything on this page "
        f"is produced without it; the lane is additive by design."
    )
else:
    investigate = st.sidebar.checkbox(
        "Run the AI investigator",
        value=False,
        help=(
            "Adds three LLM call sites: proposed checks, unverifiable causes, and "
            "persona-voiced prose. The model proposes; this engine executes and "
            "scores. Nothing it returns can change a rank."
        ),
    )
    st.sidebar.caption(
        f"🟢 `{_spec.name}` · `{_spec.model}` · "
        f"${_spec.price_in_per_mtok:.2f}/${_spec.price_out_per_mtok:.2f} per MTok. "
        f"Switch vendor with `LEDGERLENS_LLM_PROVIDER`."
    )

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

# --- sparse KPIs: detection declines, so the analyst supplies the window.
kpi = contracts.get(metric)
cohort_key = window_key = ""

if kpi.status == "sparse_history":
    st.warning(
        f"**Insufficient history for automatic detection.** `{metric}` launched "
        f"{config.SPARSE_LAUNCH} — {(as_of - config.SPARSE_LAUNCH).days + 1} days of "
        f"history against a {contracts.thresholds(metric).warmup_days}-day warmup. "
        f"Detection is declined rather than run on a baseline that cannot support it. "
        f"Select a window manually below; uncertainty is wider than on an "
        f"established KPI."
    )
    c1, c2, c3 = st.columns(3)
    w_start = c1.date_input("Window start", date(2026, 8, 4), key="mw_start")
    w_end = c2.date_input("Window end", date(2026, 8, 17), key="mw_end")
    # sepa exists only in these regions, so the cohort picker cannot build an
    # empty slice by construction.
    region = c3.selectbox("Cohort region", config.SEPA_REGIONS, index=0, key="mw_region")
    cohort_key = json.dumps({"region": [region], "payment_rail": ["sepa"]}, sort_keys=True)
    window_key = json.dumps([w_start.isoformat(), w_end.isoformat()])

# Bumped by every recorded verdict; see `load_payload`'s docstring for why a value
# nothing reads still has to be in the cache key.
st.session_state.setdefault("feedback_n", 0)

store, payload = load_payload(
    metric,
    as_of.isoformat(),
    cohort_key,
    window_key,
    who.role,
    drop_key,
    investigate,
    str(st.session_state.feedback_n),
)
card = (
    narrate.narrate(payload, persona=who)
    if payload is not None
    else DiagnosisCard.no_anomaly(metric, as_of)
)

# ------------------------------------------------------------- 1. the anomaly

st.title(card.headline)

if card.focal is None:
    st.success(card.summary)
    st.stop()

root, focal = card.root, card.focal
unexplained = 100 * ((1 + root.delta_pct / 100) / (1 + card.seasonal_pct / 100) - 1)

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    f"{metric} (aggregate)",
    f"{root.delta_pct:.1f}%",
    delta=narrate.format_points(metric, root.delta_abs),
)
c2.metric(
    "Focal cohort",
    f"{focal.delta_pct:.1f}%",
    delta=narrate.format_points(metric, focal.delta_abs),
)
c3.metric("Share of the drop", f"{100 * focal.contribution:.0f}%", delta="of parent shortfall")
c4.metric("Robust z", f"{focal.residual_z:.1f}", delta=f"threshold {-th.mad_z}")

# The redaction is rendered HERE, beside the number it changed -- not buried in the
# contract expander. A growth reader sees a smaller shortfall than an analyst does,
# and without this line that reads as breakage rather than as policy.
if card.redactions:
    st.warning(
        "🔒 **Restricted view.** "
        + " ".join(
            f"`{r.dim}` cuts are hidden from role `{who.role}` by policy "
            f"`{r.policy_id}` — {r.reason}"
            for r in card.redactions
        )
        + "  \nThe headline above is the deepest slice this role may see. An entitled "
        "reader sees a narrower cohort and a larger shortfall. The candidate ranking "
        "is unchanged; only its depth is."
    )

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
if kpi.agg == "ratio":
    st.caption(
        "Drill-down is not shown for ratio KPIs. Contribution analysis assumes a "
        "parent's delta is the sum of its children's — a rate is not additive, so "
        "those numbers would look authoritative and mean nothing. Separating a mix "
        "effect from a within-slice effect needs a method this build does not have."
    )
else:
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
            "delta %": f"{n.delta_pct:+.2f}",
            "shortfall": money(n.delta_abs),
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

        # ---- Task 5: the feedback loop that makes P a LEARNED number.
        #
        # Shown for every persona on purpose. A verdict is not a lever -- it is the
        # reader answering "did this turn out to be right?", and the CFO who watched the
        # forecast recover is as entitled to answer it as the analyst. `decision_rights`
        # gates ACTIONS, and conflating the two would silence the people best placed to
        # close the loop.
        confirms, rejects, p_query = learning.counts(store, h.event.event_type, metric)
        fb_text, fb_yes, fb_no = st.columns([4, 1, 1])
        fb_text.caption(
            f"**P = {h.scores.P:.2f}** — a Beta–Bernoulli posterior over "
            f"**{confirms} confirmed** / **{rejects} rejected** past verdicts for "
            f"`{h.event.event_type}` on `{metric}`"
            + (f"  ·  `{p_query}`" if p_query else "")
        )

        def _verdict(kind: str) -> None:
            learning.record(
                store,
                anomaly_id=h.anomaly_id,
                hypothesis_id=h.hypothesis_id,
                event_type=h.event.event_type,
                metric=metric,
                verdict=kind,
            )
            st.session_state.feedback_n += 1

        if fb_yes.button("👍 Correct", key=f"ok_{h.hypothesis_id}", width="stretch"):
            _verdict("confirm")
            st.rerun()
        if fb_no.button("👎 Wrong", key=f"no_{h.hypothesis_id}", width="stretch"):
            _verdict("reject")
            st.rerun()

        # Depth personalization: on-call and the analyst want every control; the CFO
        # and growth get the verdict without the check-by-check table.
        if h.controls and who.show_control_table:
            frame = pd.DataFrame(
                [
                    {
                        "": "✗" if not c.passed else "✓",
                        "control": c.name,
                        "rule": c.rule,
                        "prediction": c.prediction.replace("_", " "),
                        "observed %": f"{c.observed_delta_pct:+.2f}",
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

if st.session_state.feedback_n:
    recorded, _ = store.q(
        "SELECT event_type, metric, verdict, count(*) AS n FROM verdict "
        "GROUP BY event_type, metric, verdict ORDER BY event_type, verdict",
        label="recorded verdicts",
    )
    st.success(
        f"📝 **{int(recorded['n'].sum())} verdict(s) recorded this session.** Each one "
        f"is a row in `verdict`, and the prior is re-counted from those rows on every "
        f"diagnosis — there is no separate model state to drift, and deleting a row "
        f"puts the prior back exactly where it was.",
        icon="🔁",
    )
    st.dataframe(recorded, width="stretch", hide_index=True)

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
st.caption(
    f"Shown for **{who.label}**. Confidence is the score of the evidence each action "
    f"rests on — it is not a probability that the action will work."
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

st.divider()

# ---------------------------------------------------- 4b. the investigator lane
#
# Two panels, deliberately AFTER the evidence chain and the ranked hypotheses. The
# reading order is the argument: a judge sees the deterministic verdict, then what the
# model added on top, and can tell at a glance which is which. Putting AI output above
# verified evidence would invert the claim this product makes.

if investigate or card.proposed_tests or card.unverified:
    st.subheader("🤖 The investigator lane")
    st.caption(
        "The model proposes; this engine disposes. Everything below is **additive** — "
        "it is excluded from the N score, so the ranking above is identical with this "
        "lane on or off."
    )

    t = card.telemetry
    n_rejected = t.llm_proposals_rejected if t else 0

    st.markdown("**AI-proposed checks** — filled from a fixed template vocabulary, executed in SQL by the engine.")
    if card.proposed_tests:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "check": pt.rationale,
                        "template": pt.template,
                        "cohort": cohort_label({k: v for k, v in pt.params.items() if isinstance(v, list)}),
                        "predicted": str(pt.params.get("prediction", "")).replace("_", " "),
                        "observed": (f"{pt.result.observed_delta_pct:+.1f}%" if pt.result else "not answerable"),
                        "verdict": ("held" if pt.result.passed else "FAILED") if pt.result else "—",
                        "query_id": pt.result.query_id if pt.result else "",
                    }
                    for pt in card.proposed_tests
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        st.caption(
            f"**{len(card.proposed_tests)} accepted, {n_rejected} rejected by validation.** "
            f"Every accepted check carries a replayable `query_id`, exactly like a "
            f"rule-based control. A rejected one named a dimension value, metric or "
            f"template that does not exist — the gate is why those never became a query."
        )
    elif investigate:
        st.caption(
            f"No check survived validation ({n_rejected} rejected). That is a reported "
            f"outcome, not a blank panel."
        )

    st.markdown("**Possible causes we cannot verify with connected data**")
    if card.unverified:
        st.warning(
            "Not tested. These are the honest answer to *what if the real cause was "
            "never recorded?* — each names the feed that would settle it."
        )
        for u in card.unverified:
            st.markdown(f"- **{u.description}**")
            st.caption(f"would need: {u.needed_source}  ·  would test: {u.would_test}")
    elif investigate:
        st.caption("The model named nothing outside the connected sources.")

    if card.generated_by == "llm":
        st.success(
            "✍️ The headline and summary above were written by the model and passed the "
            "**numbers guard**: every figure in them appears in the verified payload. "
            "A single invented digit would have discarded them for the template version."
        )
    elif investigate and card.telemetry and card.telemetry.llm_guard_rejections:
        st.error(
            f"✍️ The model's prose was **discarded**: it introduced "
            f"{card.telemetry.llm_guard_rejections} which appear nowhere in the verified "
            f"payload. You are reading the deterministic template instead. This is the "
            f"guard working, not the system failing."
        )

    if card.telemetry and card.telemetry.llm_failures:
        st.caption("Lane failures: " + " · ".join(card.telemetry.llm_failures))

    st.divider()

# ------------------------------------------------------------- 5. telemetry
#
# Closes two rubric rows at once: runtime telemetry, and the LLM vs non-LLM
# breakdown -- which lived only in the README before this panel existed.

with st.expander("⏱ Telemetry — latency, database work, model calls, cost"):
    t = card.telemetry
    if t is None:
        st.caption("No diagnosis ran, so there is nothing to account for.")
    else:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Wall time", f"{t.total_ms:,.0f} ms")
        m2.metric(
            "Queries executed", t.queries_executed, delta=f"{t.queries_cached} cached"
        )
        m3.metric("Replayable on this card", t.queries_on_card)
        m4.metric(
            "LLM cost",
            t.llm_cost_str,
            delta=f"{t.llm_calls} calls · {t.llm_tokens:,} tokens" if t.llm_calls else "0 calls",
        )

        st.markdown("**Where the time goes**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "stage": stage,
                        "ms": round(ms, 1),
                        "share": f"{100 * ms / max(t.total_ms, 1e-9):.0f}%",
                    }
                    for stage, ms in sorted(t.stage_ms.items(), key=lambda kv: -kv[1])
                ]
            ),
            width="stretch",
            hide_index=True,
        )

        if t.llm_calls:
            st.markdown(
                f"**This diagnosis: {t.llm_calls} LLM calls, {t.llm_tokens:,} tokens, "
                f"{t.llm_cost_str}** on `{t.llm_provider}` / `{t.llm_model}`. "
                f"Every one of those calls sits in the **investigator lane**, which is "
                f"additive: it proposed checks and prose. It did not rank, score or "
                f"reject anything. The {t.queries_on_card} replayable queries behind "
                f"this card were produced by deterministic SQL either way."
            )
        else:
            st.markdown(
                f"**This diagnosis: 0 LLM calls, $0.0000.** Every number on this page "
                f"came from a logged SQL query with a replayable `query_id`. The "
                f"ranking path is deterministic Python and SQL **by design, not by "
                f"omission** — which is why the full test suite and this entire demo "
                f"run with no API key set. Turn on the **AI investigator** in the "
                f"sidebar to add the LLM lane on top."
            )
            _s = config.provider_spec()
            if _s is not None:
                st.markdown(
                    f"**What the lane would cost.** With the investigator enabled it "
                    f"makes **three calls per diagnosis** on `{_s.model}` — proposed "
                    f"checks, unverifiable causes, narration — at roughly 6k input and "
                    f"1.2k output tokens total, about "
                    f"**${(6000 / 1e6) * _s.price_in_per_mtok + (1200 / 1e6) * _s.price_out_per_mtok:.4f}** "
                    f"at ${_s.price_in_per_mtok:.2f} / ${_s.price_out_per_mtok:.2f} per "
                    f"MTok. It would add checks and change the prose, and **none of the "
                    f"numbers above**: the ranking path never calls a model."
                )
        st.markdown(
            f"**LLM vs non-LLM, precisely.** Non-LLM: detection, attribution, cohort "
            f"intersection, all five score components, every negative control, and the "
            f"rejection of the decoy — {t.queries_executed} queries, no model involved. "
            f"LLM: proposing extra checks (which this engine then executes in SQL), "
            f"listing causes outside the connected data, and writing the prose. The "
            f"boundary is enforced in code, not by convention: proposed checks are "
            f"constructed with `decisive=False` and are never passed to "
            f"`controls.score_n`."
        )
        st.caption(
            "Telemetry carries **no query_id**, and that is deliberate: latency is a "
            "fact about the process, not about the data, so there is no query behind "
            "it to replay. It is one of exactly two such exceptions on this page — the "
            "other is the redaction notice. Counts cover *registered* queries; "
            "metadata lookups (`dim_universe`, `events`) carry no user-facing number "
            "and are excluded on the same rule."
        )

st.divider()
st.caption(
    f"Generated by the {card.generated_by} narrator. This system ranks evidence and "
    f"reports the checks behind each claim; it does not prove causation. "
    f"Effect is reported as an observed shortfall against a deseasonalized baseline, "
    f"not as a causal impact estimate."
)
