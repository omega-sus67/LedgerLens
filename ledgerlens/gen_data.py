"""Deterministic synthetic data generator.

Ground truth is known by construction, which is what lets the test suite assert the
ranking is *right* rather than merely stable.

The one hard requirement (spec 4.3) is that the aggregate renewals delta land inside
[-8.6%, -7.8%]. Hand-tuning a seeded RNG into a 0.8pp band is the single biggest
time sink in this build, so we do not: two scaling constants are SOLVED in closed
form against the realized (post-noise) window sums, which makes the target share --
and therefore the aggregate delta -- exact by construction rather than statistical.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import config

# Relative slice weights. Declared rather than drawn, so the revenue distribution is
# inspectable; the lognormal jitter below is cosmetic realism, not a tuning lever.
REGION_W = {"DACH": 1.6, "UK": 1.2, "FR": 1.0, "US": 1.8, "APAC": 0.8, "Nordics": 0.6}
SEGMENT_W = {"Enterprise": 6.0, "Mid": 2.0, "SMB": 1.0}
RAIL_W = {"sepa": 1.0, "card": 1.0, "invoice": 0.8}
PRODUCT_W = {"A": 1.0, "B": 0.7, "C": 0.5}


def live_slices() -> list[tuple[str, str, str, str]]:
    """The (region, segment, payment_rail, product) tuples that actually exist.

    Implausible combinations are suppressed to keep the fixture realistic:
    sepa only in SEPA_REGIONS, invoice only for Enterprise. 99 slices survive.
    """
    out = []
    for region in config.DIMENSIONS["region"]:
        for segment in config.DIMENSIONS["segment"]:
            for rail in config.DIMENSIONS["payment_rail"]:
                if rail == "sepa" and region not in config.SEPA_REGIONS:
                    continue
                if rail == "invoice" and segment not in config.INVOICE_SEGMENTS:
                    continue
                for product in config.DIMENSIONS["product"]:
                    out.append((region, segment, rail, product))
    return sorted(out)


def _is_quarter_end(d: date) -> bool:
    if d.month not in (3, 6, 9, 12):
        return False
    last = (date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1)).day
    return d.day > last - 3


def _matches(slice_: tuple[str, str, str, str], cohort: dict[str, list[str]]) -> bool:
    region, segment, rail, product = slice_
    values = {"region": region, "segment": segment, "payment_rail": rail, "product": product}
    return all(values[dim] in allowed for dim, allowed in cohort.items())


# --------------------------------------------------------------------- metrics


def _raw_panel(slices, dates, rng, scale: float) -> np.ndarray:
    """base x trend x weekly x quarter-end x noise. No seasonality dip, no injection."""
    n_s, n_d = len(slices), len(dates)
    t = np.arange(n_d, dtype=float)

    weights = np.array(
        [REGION_W[r] * SEGMENT_W[s] * RAIL_W[p] * PRODUCT_W[pr] for r, s, p, pr in slices]
    )
    weights = weights * rng.lognormal(0.0, config.JITTER_SD, size=n_s)
    base = scale * weights / weights.sum()

    phase = rng.uniform(0.0, 2 * math.pi, size=n_s)
    weekly = 1 + config.WEEKLY_AMPLITUDE * np.sin(
        2 * math.pi * t[None, :] / 7 + phase[:, None]
    )
    trend = 1 + config.TREND_PER_DAY * t
    quarter = np.array([config.QUARTER_END_MULT if _is_quarter_end(d) else 1.0 for d in dates])
    noise = rng.normal(1.0, config.NOISE_SD, size=(n_s, n_d))

    return base[:, None] * trend[None, :] * weekly * quarter[None, :] * noise


def generate(out_dir: Path | str = config.DATA_DIR) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(config.SEED)

    slices = live_slices()
    dates = pd.date_range(config.GEN_START, config.GEN_END, freq="D").date.tolist()
    n_d = len(dates)

    august = np.array([config.AUGUST_DIP if d.month == 8 else 1.0 for d in dates])
    is_target = np.array([_matches(s, config.TARGET_COHORT) for s in slices])
    win_lo, win_hi = config.TUNE_WINDOW
    in_window = np.array([win_lo <= d <= win_hi for d in dates])
    post_onset = np.array([d >= config.ONSET for d in dates])

    raw = _raw_panel(slices, dates, rng, config.TOTAL_DAILY_BASE)

    # --- solve k so the target slices hold exactly TARGET_SHARE of window revenue.
    # The August multiplier is uniform across slices inside the window, so it cancels
    # from the ratio and can be ignored here. Noise, trend, weekly phase and jitter
    # are already baked into these realized sums, so they cannot move the answer.
    r_tgt = raw[is_target][:, in_window].sum()
    r_rest = raw[~is_target][:, in_window].sum()
    f = config.TARGET_SHARE
    k = (f / (1 - f)) * (r_rest / r_tgt)
    raw[is_target] *= k

    # --- solve G so the headline shortfall is exactly TARGET_IMPACT_ABS.
    # Scaling every slice equally leaves the share above untouched.
    expected_target_window = (raw[is_target][:, in_window] * config.AUGUST_DIP).sum()
    shortfall = -(1 - config.KILL_MULTIPLIER) * expected_target_window
    raw *= config.TARGET_IMPACT_ABS / shortfall

    injection = np.where(
        is_target[:, None] & post_onset[None, :], config.KILL_MULTIPLIER, 1.0
    )
    untreated_noaug = raw
    untreated_withaug = raw * august[None, :]
    renewals = untreated_withaug * injection

    # --- new_logo_bookings: same slice universe (spec 16 #2 -- a metric-blind row
    # count would otherwise inflate |B| for blast radii unconstrained on metric).
    raw_logo = _raw_panel(slices, dates, rng, config.TOTAL_DAILY_BASE * config.NEW_LOGO_SCALE)
    in_dach = np.array([s[0] == "DACH" for s in slices])
    post_campaign = np.array([d >= config.CAMPAIGN_START for d in dates])
    campaign_mult = np.where(
        in_dach[:, None] & post_campaign[None, :], config.CAMPAIGN_MULTIPLIER, 1.0
    )
    bookings = raw_logo * august[None, :] * campaign_mult

    _write_metrics(out_dir, slices, dates, renewals, bookings)
    _write_sparse_metric(out_dir, slices)

    # --- measured ground truth (never assumed)
    treated_win = renewals[:, in_window].sum()
    withaug_win = untreated_withaug[:, in_window].sum()
    noaug_win = untreated_noaug[:, in_window].sum()
    impact = (renewals[is_target][:, in_window] - untreated_withaug[is_target][:, in_window]).sum()

    truth = {
        "true_cause_event_id": "deploy_sepa_v214",
        "true_cohort": config.TARGET_COHORT,
        "onset": config.ONSET.isoformat(),
        "window": [win_lo.isoformat(), win_hi.isoformat()],
        "expected_agg_delta_pct_range": [-8.6, -7.8],
        # observed = what a baseline fitted on pre-August data sees: seasonality + deploy
        "observed_agg_delta_pct": round(100 * (treated_win / noaug_win - 1), 4),
        # deploy_only = measured against a counterfactual that keeps August seasonality
        "deploy_only_delta_pct": round(100 * (treated_win / withaug_win - 1), 4),
        "seasonal_delta_pct": round(100 * (config.AUGUST_DIP - 1), 4),
        "true_impact_abs": round(float(impact), 2),
        "target_share": round(
            float(untreated_withaug[is_target][:, in_window].sum() / withaug_win), 6
        ),
        "n_live_slices": len(slices),
        "n_target_slices": int(is_target.sum()),
        "sparse_metric": "payment_success_rate",
        "sparse_launch": config.SPARSE_LAUNCH.isoformat(),
        "sparse_days_generated": len(
            pd.date_range(config.SPARSE_LAUNCH, config.GEN_END, freq="D")
        ),
        "sparse_dip_cohort": config.PSR_DIP_COHORT,
        "sparse_dip_onset": config.PSR_DIP_START.isoformat(),
        "decoys": ["campaign_dach_cut", "pricing_us_q3"],
        "must_not_rank_top": ["campaign_dach_cut"],
    }

    _write_events(out_dir)
    _write_tickets(out_dir, rng)
    _write_slack(out_dir)
    (out_dir / "ground_truth.json").write_text(json.dumps(truth, indent=2) + "\n")
    return truth


def _write_metrics(out_dir, slices, dates, renewals, bookings) -> None:
    frames = []
    for name, panel in (("mrr_renewals", renewals), ("new_logo_bookings", bookings)):
        n_s, n_d = panel.shape
        frames.append(
            pd.DataFrame(
                {
                    "date": np.tile(dates, n_s),
                    "metric_name": name,
                    "region": np.repeat([s[0] for s in slices], n_d),
                    "segment": np.repeat([s[1] for s in slices], n_d),
                    "payment_rail": np.repeat([s[2] for s in slices], n_d),
                    "product": np.repeat([s[3] for s in slices], n_d),
                    "value": panel.reshape(-1),
                }
            )
        )
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df.to_parquet(out_dir / "metrics.parquet", index=False)


def _sparse_panels(slices, dates) -> tuple[np.ndarray, np.ndarray]:
    """payment_success_rate, stored as the two ADDITIVE metrics behind it.

    A rate cannot live in an additive fact table -- SUM(value) across 99 slices would
    give ~97 -- so we store successes and attempts and let the contract divide them.
    See docs/sparse_kpi_decisions.md.

    Draws from its OWN RNG stream (config.SEED_SPARSE). Do NOT pass the shared `rng`
    here: generate() draws renewals, then bookings, then tickets from one sequential
    stream, and an extra draw would shift everything after it.
    """
    rng = np.random.default_rng(config.SEED_SPARSE)
    n_s, n_d = len(slices), len(dates)

    attempts = np.round(
        rng.lognormal(math.log(config.PSR_ATTEMPTS_PER_SLICE_DAY), 0.25, size=(n_s, n_d))
    )

    rate = config.PSR_BASE_RATE + rng.normal(0.0, config.PSR_NOISE_SD, size=(n_s, n_d))

    # The same SEPA connector release, seen through a different KPI. The dip is real
    # and material, but the metric is too young for the detector to be allowed to find
    # it -- which is the scenario this KPI exists to demonstrate.
    hit = np.array([_matches(s, config.PSR_DIP_COHORT) for s in slices])
    post = np.array([d >= config.PSR_DIP_START for d in dates])
    rate = np.where(hit[:, None] & post[None, :], config.PSR_DIP_RATE, rate)

    rate = np.clip(rate, 0.0, 1.0)
    return np.round(attempts * rate), attempts


def _write_sparse_metric(out_dir: Path, slices) -> None:
    """Append the sparse KPI's two physical metrics to metrics.parquet.

    Its date range is SHORTER than the other metrics' on purpose: history begins at
    config.SPARSE_LAUNCH, well below DETECT_WARMUP_DAYS, so detect() declines and the
    card has to say why.
    """
    dates = pd.date_range(config.SPARSE_LAUNCH, config.GEN_END, freq="D").date.tolist()
    successes, attempts = _sparse_panels(slices, dates)
    n_d = len(dates)

    frames = []
    for name, panel in (("payment_successes", successes), ("payment_attempts", attempts)):
        frames.append(
            pd.DataFrame(
                {
                    "date": np.tile(dates, len(slices)),
                    "metric_name": name,
                    "region": np.repeat([s[0] for s in slices], n_d),
                    "segment": np.repeat([s[1] for s in slices], n_d),
                    "payment_rail": np.repeat([s[2] for s in slices], n_d),
                    "product": np.repeat([s[3] for s in slices], n_d),
                    "value": panel.reshape(-1),
                }
            )
        )
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.date

    existing = pd.read_parquet(out_dir / "metrics.parquet")
    pd.concat([existing, df], ignore_index=True).to_parquet(
        out_dir / "metrics.parquet", index=False
    )


# ---------------------------------------------------------------------- events


def _write_events(out_dir: Path) -> None:
    """Source-shaped payloads. Blast radius is DERIVED by connectors.py from declared
    metadata (rollout regions, flag targeting, campaign geo) -- never inferred."""
    deploys = [
        {
            "sha": "deploy_sepa_v214",
            "merged_at": "2026-08-03T02:00:00",
            "service": "payments-sepa-connector",
            "regions": ["DACH"],
            "rails": ["sepa"],
            "title": "SEPA direct-debit connector v2.1.4 (retry/timeout rework)",
            "url": "https://github.example/payments/pull/2141",
        },
        {
            "sha": "deploy_dunning_v3",
            "merged_at": "2026-07-30T09:15:00",
            "service": "billing-dunning",
            "regions": ["DACH", "UK"],
            "rails": [],
            "title": "Dunning schedule v3",
            "url": "https://github.example/billing/pull/883",
        },
        {
            "sha": "deploy_billing_ui_v9",
            "merged_at": "2026-07-28T14:00:00",
            "service": "billing-ui",
            "regions": ["*"],
            "rails": [],
            "title": "Billing portal redesign v9",
            "url": "https://github.example/billing-ui/pull/512",
        },
        {
            "sha": "deploy_apac_cache",
            "merged_at": "2026-08-05T06:30:00",
            "service": "edge-cache",
            "regions": ["APAC"],
            "rails": [],
            "title": "APAC edge cache warmup",
            "url": "https://github.example/edge/pull/77",
        },
        {
            "sha": "deploy_us_tax_v2",
            "merged_at": "2026-08-01T11:00:00",
            "service": "tax-engine",
            "regions": ["US"],
            "rails": [],
            "title": "US sales-tax engine v2",
            "url": "https://github.example/tax/pull/301",
        },
        {
            "sha": "deploy_uk_invoice_pdf",
            "merged_at": "2026-07-27T16:45:00",
            "service": "invoice-render",
            "regions": ["UK"],
            "rails": ["invoice"],
            "title": "UK invoice PDF template refresh",
            "url": "https://github.example/invoice/pull/145",
        },
        {
            "sha": "deploy_nordics_vat",
            "merged_at": "2026-07-16T08:00:00",
            "service": "tax-engine",
            "regions": ["Nordics"],
            "rails": [],
            "title": "Nordics VAT rate table update",
            "url": "https://github.example/tax/pull/297",
        },
        {
            "sha": "deploy_search_reindex",
            "merged_at": "2026-07-05T03:00:00",
            "service": "search",
            "regions": ["*"],
            "rails": [],
            "title": "Search reindex pipeline",
            "url": "https://github.example/search/pull/61",
        },
        {
            "sha": "deploy_auth_rotate",
            "merged_at": "2026-07-02T22:10:00",
            "service": "auth",
            "regions": ["*"],
            "rails": [],
            "title": "Rotate service-account credentials",
            "url": "https://github.example/auth/pull/19",
        },
    ]
    flags = [
        {
            "key": "flag_sepa_retry_beta",
            "enabled_at": "2026-08-06T10:00:00",
            "targeting": {"rails": ["sepa"]},
            "description": "Beta: aggressive SEPA retry backoff",
        },
        {
            "key": "flag_new_dash_ui",
            "enabled_at": "2026-07-22T12:00:00",
            "targeting": {"segments": ["SMB"]},
            "description": "New dashboard shell for SMB",
        },
    ]
    campaigns = [
        {
            "name": "campaign_dach_cut",
            "start": "2026-08-02",
            "end": None,
            "geo": ["DACH"],
            "objective": "acquisition",
            "description": "DACH paid acquisition budget cut 40%",
        }
    ]
    pricing = [
        {
            "sku": "pricing_us_q3",
            "region": "US",
            "old": 199.0,
            "new": 229.0,
            "effective": "2026-08-02",
            "description": "US Pro list price +15% for Q3",
        }
    ]
    (out_dir / "events_deploys.json").write_text(json.dumps(deploys, indent=2) + "\n")
    (out_dir / "events_flags.json").write_text(json.dumps(flags, indent=2) + "\n")
    (out_dir / "events_campaigns.json").write_text(json.dumps(campaigns, indent=2) + "\n")
    (out_dir / "events_pricing.json").write_text(json.dumps(pricing, indent=2) + "\n")


# --------------------------------------------------------------------- tickets

# Baseline subjects deliberately exercise every filler word that appears in the
# injected prose subjects. That leaves exactly {sepa, debit, timeout} unseen before
# the anomaly window, so the IDF-based key derivation in symptoms.py lands on the
# same three tokens for all 21 prose tickets by construction -- no fuzzy threshold.
BASELINE_SUBJECTS = {
    "ERR_TIMEOUT": [
        "Payment gateway error on checkout",
        "Customer payment retry failing",
        "Gateway error blocking checkout",
    ],
    "BILLING_Q": [
        "Question about renewal charge",
        "Customer account renewal charge query",
        "Billing charge question during renewal",
    ],
    "LOGIN": [
        "Customer account login failing",
        "Account login keeps hitting error",
        "Login error blocking direct access",
    ],
    "FEATURE_REQ": [
        "Feature request direct export",
        "Request for direct account export",
        "Feature request during renewal",
    ],
}

PROSE_SUBJECTS = [
    "SEPA direct debit timeout during renewal charge",
    "Customer account SEPA debit keeps hitting timeout",
    "SEPA debit retry timeout at checkout",
    "Direct debit SEPA payment timeout error",
    "SEPA debit gateway timeout on renewal",
    "Failing SEPA direct debit timeout",
    "SEPA debit timeout blocking customer payment",
]

PROSE_BODIES = [
    "Our direct debit keeps timing out at checkout. Nothing has changed on our side.",
    "Renewal collection is failing repeatedly -- the bank mandate looks fine.",
    "Direct debit attempts hang for about 30 seconds and then drop.",
    "Finance flagged that this month's collection never completed.",
    "We have retried three times today; each attempt stalls and then errors out.",
]


def _write_tickets(out_dir: Path, rng: np.random.Generator) -> None:
    tickets = []
    n = 0

    baseline_days = (config.TUNE_WINDOW[1] - config.TICKET_BASELINE_START).days + 1
    keys = sorted(BASELINE_SUBJECTS)
    regions = config.DIMENSIONS["region"]
    segments = config.DIMENSIONS["segment"]
    for i in range(baseline_days):
        day = config.TICKET_BASELINE_START + timedelta(days=i)
        for _ in range(config.TICKET_BASELINE_PER_DAY):
            key = keys[int(rng.integers(len(keys)))]
            subject = BASELINE_SUBJECTS[key][int(rng.integers(3))]
            n += 1
            tickets.append(
                {
                    "ticket_id": f"T-{n:05d}",
                    "created_at": datetime.combine(day, datetime.min.time())
                    .replace(hour=int(rng.integers(8, 19)))
                    .isoformat(),
                    "account_id": f"ACC-{int(rng.integers(1, 400)):04d}",
                    "region": regions[int(rng.integers(len(regions)))],
                    "segment": segments[int(rng.integers(len(segments)))],
                    "subject": subject,
                    "body": "Standard support request.",
                    "error_code": key,
                }
            )

    # injected spike: half coded, half prose-only (spec 4.3)
    per_day = config.INJECTED_TICKETS // config.INJECTED_TICKET_DAYS
    idx = 0
    for i in range(config.INJECTED_TICKET_DAYS):
        day = config.ONSET + timedelta(days=i)
        for _ in range(per_day):
            coded = idx % 2 == 0
            n += 1
            idx += 1
            tickets.append(
                {
                    "ticket_id": f"T-{n:05d}",
                    "created_at": datetime.combine(day, datetime.min.time())
                    .replace(hour=int(rng.integers(6, 21)))
                    .isoformat(),
                    "account_id": f"ACC-{int(rng.integers(1, 120)):04d}",
                    "region": "DACH",
                    "segment": "Enterprise",
                    "subject": (
                        "SEPA direct debit failed with ERR_SEPA_504"
                        if coded
                        else PROSE_SUBJECTS[idx % len(PROSE_SUBJECTS)]
                    ),
                    "body": (
                        "Gateway returned ERR_SEPA_504 on the direct debit collection."
                        if coded
                        else PROSE_BODIES[idx % len(PROSE_BODIES)]
                    ),
                    "error_code": "ERR_SEPA_504" if coded else None,
                }
            )

    (out_dir / "tickets.json").write_text(json.dumps(tickets, indent=2) + "\n")


def _write_slack(out_dir: Path) -> None:
    msgs = [
        {
            "msg_id": "M-0001",
            "ts": "2026-08-03T03:14:00",
            "channel": "#ops-payments",
            "author": "oncall-payments",
            "text": "Frankfurt cluster SEPA latency spiking post-deploy, mandate collection timing out",
            "permalink": "https://slack.example/archives/ops-payments/p1",
        },
        {
            "msg_id": "M-0002",
            "ts": "2026-08-09T11:02:00",
            "channel": "#finance",
            "author": "fp-and-a",
            "text": "Renewals pacing looks well below plan this month, anyone know why?",
            "permalink": "https://slack.example/archives/finance/p2",
        },
    ]
    filler = [
        "Standup notes posted",
        "Anyone free to review the runbook?",
        "Coffee machine is down again",
        "Reminder: quarterly security training due Friday",
        "Deploy freeze lifts Monday",
        "Onsite with the Nordics team next week",
        "Docs site build is green",
        "Who owns the invoice template repo?",
        "Lunch and learn moved to 13:00",
        "New starter joining the platform squad",
        "Grafana dashboard permissions fixed",
        "Retro action items updated",
        "Please update your PTO calendar",
        "The staging env is flaky again",
        "Design review pushed to Thursday",
        "Customer webinar recording is up",
        "Sprint board groomed",
        "Pager rotation swapped for next week",
        "Terraform plan needs a second pair of eyes",
        "Reminder to expense your travel",
        "Postmortem template updated",
        "Office wifi maintenance tonight",
        "Welcome to the new analytics channel",
    ]
    base = datetime(2026, 7, 20, 9, 0)
    for i, text in enumerate(filler):
        msgs.append(
            {
                "msg_id": f"M-{i + 3:04d}",
                "ts": (base + timedelta(hours=7 * i)).isoformat(),
                "channel": "#general",
                "author": f"user{i % 7}",
                "text": text,
                "permalink": f"https://slack.example/archives/general/p{i + 3}",
            }
        )
    (out_dir / "slack.json").write_text(json.dumps(msgs, indent=2) + "\n")


if __name__ == "__main__":
    truth = generate()
    print(json.dumps(truth, indent=2))
