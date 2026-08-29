"""Constants, paths, weights and thresholds. Everything tunable lives here.

Values marked SPEC-GAP deviate from IMPLEMENTATION_SPEC.md; each carries its reason.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

SEED = 20260815

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "ledgerlens.duckdb"

# ---------------------------------------------------------------- dimensions
DIMENSIONS: dict[str, list[str]] = {
    "region": ["DACH", "UK", "FR", "US", "APAC", "Nordics"],
    "segment": ["Enterprise", "Mid", "SMB"],
    "payment_rail": ["sepa", "card", "invoice"],
    "product": ["A", "B", "C"],
}
DRILL_DIMS = ["region", "segment", "payment_rail", "product"]
METRICS = ["mrr_renewals", "new_logo_bookings", "payment_success_rate"]

# slice suppression rules (kept realistic, per spec 4.1)
SEPA_REGIONS = ["DACH", "FR", "Nordics"]
INVOICE_SEGMENTS = ["Enterprise"]

# ------------------------------------------------- sparse-history KPI (task 3)
# Its own RNG stream. gen_data draws mrr_renewals, then new_logo_bookings, then
# tickets from ONE sequential generator, so a third draw on that stream shifts every
# subsequent value. An isolated stream makes the existing panels bit-identical by
# construction rather than by luck; tests/test_sparse_kpi.py fingerprints them.
SEED_SPARSE = 20260816

# Launch date, chosen against the demo's as-of (2026-08-17), NOT against GEN_END.
# fit_pre_window() requires >= 30 pre-window days. A 14-day manual window ending at
# as_of starts 2026-08-04, so data must begin by 2026-07-05 for the MANUAL path to
# work at all. 2026-06-23 gives 55 days to as_of (41 pre-window days -- real margin)
# and 70 to GEN_END, both far below DETECT_WARMUP_DAYS = 120, so automatic detection
# still declines. "~45 days" does NOT work: 17 pre-window days, and the manual path
# fails too, leaving a KPI that can do nothing at all.
SPARSE_LAUNCH = date(2026, 6, 23)

PSR_BASE_RATE = 0.982  # steady-state authorisation success
PSR_ATTEMPTS_PER_SLICE_DAY = 140.0  # scale for the denominator
PSR_NOISE_SD = 0.004  # day-to-day wobble in the rate
PSR_DIP_START = date(2026, 8, 3)  # the same onset as the SEPA deploy
PSR_DIP_COHORT = {"region": ["DACH"], "payment_rail": ["sepa"]}
PSR_DIP_RATE = 0.913  # what the affected cohort falls to

# ---------------------------------------------------------------- anomaly
MAD_Z_THRESHOLD = 3.5  # robust z on rolling-median residual
MIN_CONSECUTIVE_PERIODS = 2
CONTRIBUTION_FLOOR = 0.15  # child must explain >=15% of parent delta to recurse
MAX_DRILL_DEPTH = 3
STL_MIN_CYCLES = 2  # else fall back to rolling median
BH_FDR_Q = 0.10

DIRECTION = "drop"  # v1 flags negative anomalies only (spec 7.1)
MIN_SLICE_ROWS_PER_DAY = 3  # slices thinner than this are never tested
CONTRIB_DENOM_FLOOR = 0.02  # skip recursion when |parent delta| < 2% of expected

# SPEC-GAP: practical-significance gate, added on review. The August seasonal dip
# sits at z ~ -2.0 against 1 sigma of daily noise, so P(z < -3.5) is ~7%/day across
# the 31 days of Aug-2025 -- roughly a 15% chance of a spurious 2-day flag, which
# would make the `as_of=2026-07-31 -> None` acceptance test a coin flip. Requiring
# both statistical AND practical significance makes it deterministic: the seasonal
# dip is -1.2% and can never reach -3%; the injected drop is -8.2% and always does.
MIN_ABS_DELTA_PCT = 3.0

PRE_WINDOW_DAYS = 90  # trailing window for median/MAD and the baseline fit
SCAN_DAYS = 400  # detection scan span; must reach back over Aug-2025
DETECT_WARMUP_DAYS = 120  # no pre-window before this much history
WINDOW_LENGTH_DAYS = 14  # anomaly window = [onset, onset+13]

# ---------------------------------------------------------------- hypothesis
LOOKBACK_DAYS = 21  # candidate window before anomaly onset
SCORE_WEIGHTS = {"T": 0.25, "C": 0.30, "D": 0.15, "N": 0.25, "P": 0.05}
SCORE_FLOOR = 0.45  # below this, emit "no candidate explains this"
AMBIGUITY_EPSILON = 0.08  # |s1 - s2| < eps -> discriminating test

# ---------------------------------------------------------------- controls
CONTROL_PASS_BAND_PCT = 5.0  # |delta| < 5% passes a should_be_flat control

# SPEC-GAP (bug A): spec 9.2 forces N=0 only on a failing `should_be_flat` control.
# The control that kills the marketing decoy is a `should_also_drop` control that
# failed by staying FLAT, so as literally specified the decoy is never rejected and
# the phase-6 acceptance test cannot pass. `decisive_failure` in controls.py
# generalises the rule; this is the flatness threshold for the second branch.
#
# Set at half the pass band. A cohort predicted to fall by 5%+ that instead moved
# less than 2.5% did not move: it is sitting on the ~1.2% August seasonality that
# every cohort in the business shows. Between -2.5% and -5% is genuinely ambiguous,
# so those failures only lower N rather than rejecting outright.
DECISIVE_FLAT_PCT = -2.5

# SPEC-GAP (bug B): spec 9.4 rule 2 ("segment siblings should also drop") fires for
# ANY event that leaves `segment` unconstrained -- including the true cause, whose
# blast radius is {region, payment_rail}. It would build the same DACH x {Mid,SMB}
# control, see it flat, and reject the real answer. Rule 2 is therefore gated on
# mechanism class: a demand-side change to a region has no mechanism by which it
# could spare Mid/SMB customers in that region, but a deploy targets a code path,
# and enterprise direct debit IS a distinct code path. Documented in the README.
SEGMENT_AGNOSTIC_EVENT_TYPES = {
    "campaign",
    "price_change",
    "policy_change",
    "external",
    "vendor_incident",
}
PLACEBO_SHIFT_DAYS = 28  # temporal placebo control looks this far back

# ---------------------------------------------------------------- effect
BOOTSTRAP_ITERS = 2000
CI_LEVEL = 0.95

# ---------------------------------------------------------------- investigator
LLM_TEST_BUDGET = 6
EXPLORER_QUERY_BUDGET = 12
MODEL = "claude-sonnet-4-6"

# ---------------------------------------------------------------- generator
GEN_START = date(2025, 3, 1)
GEN_END = date(2026, 8, 31)
NOISE_SD = 0.045
TREND_PER_DAY = 0.00035
WEEKLY_AMPLITUDE = 0.06
QUARTER_END_MULT = 1.35
JITTER_SD = 0.10

# SPEC-GAP: spec 4.2 says 0.985 (-1.5%), spec 13's headline demands "Expected -1.2%
# (August seasonality)". 0.988 makes that line computable from the data rather than
# hardcoded. Either value lands the aggregate inside the required band.
AUGUST_DIP = 0.988

ONSET = date(2026, 8, 3)
TUNE_WINDOW = (date(2026, 8, 3), date(2026, 8, 16))
TARGET_COHORT = {"region": ["DACH"], "segment": ["Enterprise"], "payment_rail": ["sepa"]}
KILL_MULTIPLIER = 0.15  # renewals in the target cohort retain 15% from onset
TOTAL_DAILY_BASE = 420_000.0  # nominal daily scale before the solved global rescale
TARGET_SHARE = 0.0830  # solved-for share of total renewals held by the target slices
TARGET_IMPACT_ABS = -410_000.0  # generator scales globally to hit this exactly
CAMPAIGN_MULTIPLIER = 0.7  # effect of the decoy on new_logo_bookings in DACH
NEW_LOGO_SCALE = 0.25

# SPEC-GAP: spec 4.3 dates the marketing decoy Aug 4, one day AFTER onset -- which
# gives it T=0 under spec 9.2 ("event after onset: cannot cause"), drops it to last
# place, and destroys the whole point of having a decoy. Aug 2 makes it temporally
# competitive (T=0.72), which is what spec 4.3's prose actually describes.
CAMPAIGN_START = date(2026, 8, 2)

# tickets
TICKET_BASELINE_START = date(2026, 7, 8)
TICKET_BASELINE_PER_DAY = 2
INJECTED_TICKETS = 42
INJECTED_TICKET_DAYS = 6
NOVEL_TOKEN_DF_MAX = 0.10  # token counts as "novel" below this pre-window doc freq
SYMPTOM_MIN_LIFT = 3.0
SYMPTOM_MIN_VOLUME = 5
SYMPTOM_BASELINE_DAYS = 28
