"""Deterministic event ingestion. No LLM anywhere in this module.

Blast radius is a DECLARED MAPPING from metadata the source system already records
-- a deploy knows its rollout regions and rails, a flag knows its targeting rules, a
campaign knows its geo. It is never inferred from prose. In production these fields
come from deploy metadata / LaunchDarkly targeting / campaign settings; that is the
"enterprises already have this data" argument and it is the crux of the pitch.

The omission rule is load-bearing: a dimension the source does not constrain is left
OUT of the blast radius, which makes it unconstrained (matches everything). A blast
radius that is too wide fails its negative controls; one that is too narrow leaves
nothing above the score floor. Both degrade toward "I don't know", not toward a
confident wrong answer.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import config
from ledgerlens.models import ChangeEvent, Cohort, validate_cohort


def _clean(blast: Cohort) -> Cohort:
    blast = {k: sorted(v) for k, v in blast.items() if v}
    validate_cohort(blast, config.DIMENSIONS)
    return blast


def from_deploys(path: Path) -> list[ChangeEvent]:
    out = []
    for d in json.loads(Path(path).read_text()):
        blast: Cohort = {}
        if d.get("regions") and d["regions"] != ["*"]:
            blast["region"] = d["regions"]
        if d.get("rails"):
            blast["payment_rail"] = d["rails"]
        if d.get("segments"):
            blast["segment"] = d["segments"]
        out.append(
            ChangeEvent(
                event_id=d["sha"],
                event_type="deploy",
                ts_start=datetime.fromisoformat(d["merged_at"]),
                ts_end=None,
                source="github",
                blast_radius=_clean(blast),
                description=f"{d['service']}: {d['title']}",
                evidence_refs=[d["url"]],
            )
        )
    return out


def from_flags(path: Path) -> list[ChangeEvent]:
    out = []
    for f in json.loads(Path(path).read_text()):
        targeting = f.get("targeting") or {}
        blast: Cohort = {}
        if targeting.get("regions"):
            blast["region"] = targeting["regions"]
        if targeting.get("rails"):
            blast["payment_rail"] = targeting["rails"]
        if targeting.get("segments"):
            blast["segment"] = targeting["segments"]
        out.append(
            ChangeEvent(
                event_id=f["key"],
                event_type="feature_flag",
                ts_start=datetime.fromisoformat(f["enabled_at"]),
                ts_end=None,
                source="launchdarkly",
                blast_radius=_clean(blast),
                description=f"Flag enabled: {f['description']}",
                evidence_refs=[f"launchdarkly://{f['key']}"],
            )
        )
    return out


def from_campaigns(path: Path) -> list[ChangeEvent]:
    out = []
    for c in json.loads(Path(path).read_text()):
        blast: Cohort = {"region": c["geo"]} if c.get("geo") else {}
        out.append(
            ChangeEvent(
                event_id=c["name"],
                event_type="campaign",
                ts_start=datetime.fromisoformat(c["start"]),
                ts_end=datetime.fromisoformat(c["end"]) if c.get("end") else None,
                source="calendar",
                blast_radius=_clean(blast),
                description=f"{c['description']} (objective: {c['objective']})",
                evidence_refs=[f"calendar://{c['name']}"],
            )
        )
    return out


def from_pricing(path: Path) -> list[ChangeEvent]:
    out = []
    for p in json.loads(Path(path).read_text()):
        blast: Cohort = {"region": [p["region"]]} if p.get("region") else {}
        out.append(
            ChangeEvent(
                event_id=p["sku"],
                event_type="price_change",
                ts_start=datetime.fromisoformat(p["effective"]),
                ts_end=None,
                source="pricing_db",
                blast_radius=_clean(blast),
                description=f"{p['description']} ({p['old']} -> {p['new']})",
                evidence_refs=[f"pricing_db://{p['sku']}"],
            )
        )
    return out


LOADERS = {
    "events_deploys.json": from_deploys,
    "events_flags.json": from_flags,
    "events_campaigns.json": from_campaigns,
    "events_pricing.json": from_pricing,
}


def load_all(data_dir: Path | str = config.DATA_DIR) -> list[ChangeEvent]:
    data_dir = Path(data_dir)
    events: list[ChangeEvent] = []
    for filename, loader in LOADERS.items():
        path = data_dir / filename
        if path.exists():
            events.extend(loader(path))
    return sorted(events, key=lambda e: (e.ts_start, e.event_id))
