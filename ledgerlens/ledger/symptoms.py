"""Ticket clustering. Deterministic, no LLM.

Support tickets are a SYMPTOM stream, not a source of candidates. A spike in a
cluster is corroborating evidence attached to a hypothesis; it is never a root cause
in its own right. Keeping causes in the ledger and symptoms out of it is what stops
the hypothesis space from exploding.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import timedelta

import config
from ledgerlens.models import Cohort, SymptomCluster, Window, stable_id
from ledgerlens.store import Store

STOPWORDS = {
    "a", "an", "the", "on", "at", "in", "of", "for", "to", "is", "are", "and", "or",
    "with", "about", "from", "during", "by", "it", "this", "that", "was", "were",
    "our", "we", "my", "has", "have", "had", "not", "no", "up", "out", "over",
}

TOKEN_RE = re.compile(r"[^a-z]+")


def tokenize(text: str) -> list[str]:
    """lowercase, strip digits and punctuation, drop stopwords and 1-char tokens."""
    parts = TOKEN_RE.split((text or "").lower())
    return [p for p in parts if len(p) > 1 and p not in STOPWORDS]


def _corpus_df(rows: list[dict]) -> tuple[dict[str, int], int]:
    """Document frequency over the historical corpus (subjects AND error codes).

    Error codes must be in here: otherwise `timeout` looks brand new merely because
    it only ever appeared inside ERR_TIMEOUT, and the baseline timeout cluster would
    then merge with the SEPA cluster on a shared 'novel' token.
    """
    df: Counter[str] = Counter()
    for r in rows:
        seen = set(tokenize(r["subject"])) | set(tokenize(r.get("error_code") or ""))
        df.update(seen)
    return dict(df), len(rows)


def derive_key(subject: str, df: dict[str, int], n_docs: int) -> str:
    """The 3 highest-IDF subject tokens, joined.

    IDF is measured against the PRE-window corpus, so a token nobody has seen before
    ranks top. That is the property that makes the prose-only tickets ("direct debit
    keeps timing out") collapse onto the same key as the coded ones without any
    fuzzy similarity threshold: the novel tokens are identical by construction.
    Ties break alphabetically so the key is stable.
    """
    tokens = sorted(set(tokenize(subject)))
    if not tokens:
        return "unclassified"
    scored = sorted(
        tokens,
        key=lambda t: (-math.log((n_docs + 1) / (df.get(t, 0) + 1)), t),
    )
    return "_".join(sorted(scored[:3]))


def _novel_tokens(key: str, df: dict[str, int], n_docs: int) -> set[str]:
    if n_docs == 0:
        return set()
    return {t for t in tokenize(key) if df.get(t, 0) / n_docs < config.NOVEL_TOKEN_DF_MAX}


def _modal_cohort(rows: list[dict]) -> Cohort:
    """Modal (region, segment), kept only where at least 70% of tickets agree."""
    cohort: Cohort = {}
    for dim in ("region", "segment"):
        counts = Counter(r[dim] for r in rows)
        value, n = counts.most_common(1)[0]
        if n / len(rows) >= 0.70:
            cohort[dim] = [value]
    return cohort


def cluster(store: Store, window: Window) -> list[SymptomCluster]:
    frame, query_id = store.q(
        "SELECT ticket_id, created_at, region, segment, subject, error_code FROM ticket "
        "ORDER BY created_at, ticket_id",
        label="support tickets",
    )
    # pandas turns SQL NULLs into NaN, which is TRUTHY -- so a prose-only ticket
    # would keep NaN as its key instead of falling through to derivation.
    rows = [
        {**r, "error_code": None if not isinstance(r["error_code"], str) else r["error_code"]}
        for r in frame.to_dict("records")
    ]

    pre = [r for r in rows if r["created_at"].date() < window.start]
    df, n_docs = _corpus_df(pre)

    for r in rows:
        r["key"] = r["error_code"] or derive_key(r["subject"], df, n_docs)

    # --- merge coded and prose descriptions of the same failure.
    # SPEC-GAP: spec 8.3 merges on token-Jaccard >= 0.6, which a coded key
    # ("ERR_SEPA_504" -> {err, sepa}) and a prose key ({debit, sepa, timeout}) can
    # never reach against each other. Merging on a shared NOVEL token plus cohort and
    # onset agreement is both achievable and a tighter test.
    keys = sorted({r["key"] for r in rows})
    novel = {k: _novel_tokens(k, df, n_docs) for k in keys}
    by_key: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_key[r["key"]].append(r)

    parent = {k: k for k in keys}

    def find(k: str) -> str:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def better_label(a: str, b: str) -> str:
        """Prefer an explicit error code over a derived token key: it is what an
        engineer would actually search for, and it reads better on screen."""
        a_coded, b_coded = a.startswith("ERR_"), b.startswith("ERR_")
        if a_coded != b_coded:
            return a if a_coded else b
        return min(a, b)

    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            if not (novel[a] & novel[b]):
                continue
            first_a = min(r["created_at"] for r in by_key[a]).date()
            first_b = min(r["created_at"] for r in by_key[b]).date()
            if abs((first_a - first_b).days) > 3:
                continue
            if _modal_cohort(by_key[a]) != _modal_cohort(by_key[b]):
                continue
            ra, rb = find(a), find(b)
            if ra != rb:
                keep = better_label(ra, rb)
                drop = rb if keep == ra else ra
                parent[drop] = keep

    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[find(r["key"])].append(r)

    out: list[SymptomCluster] = []
    baseline_start = window.start - timedelta(days=config.SYMPTOM_BASELINE_DAYS)
    for key, members in sorted(groups.items()):
        in_window = [
            r for r in members if window.start <= r["created_at"].date() <= window.end
        ]
        if len(in_window) < config.SYMPTOM_MIN_VOLUME:
            continue
        prior = [
            r for r in members if baseline_start <= r["created_at"].date() < window.start
        ]
        # SPEC-GAP: spec 8.3 divides a window TOTAL by a per-day mean, which inflates
        # every lift by the window length and lets ordinary baseline chatter clear the
        # threshold. Compare like with like: expected count over a window of the same
        # length.
        baseline = len(prior) / config.SYMPTOM_BASELINE_DAYS * window.days
        volume = len(in_window)
        lift = volume / max(baseline, 0.5)
        if lift < config.SYMPTOM_MIN_LIFT:
            continue
        cohort = _modal_cohort(in_window)
        first_seen = min(r["created_at"] for r in in_window).date()
        out.append(
            SymptomCluster(
                cluster_id=stable_id("sym", key, window.start, window.end),
                key=key,
                cohort=cohort,
                first_seen=first_seen,
                volume=volume,
                baseline_volume=round(baseline, 3),
                lift=round(lift, 3),
                sample_refs=[r["ticket_id"] for r in in_window[:5]],
                query_id=query_id,
            )
        )
    return sorted(out, key=lambda c: -c.lift)
