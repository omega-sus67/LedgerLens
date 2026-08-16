"""DuckDB lifecycle and the query registry.

`Store.q` is the ONLY path to the database. Every number that reaches a user is
produced by it and carries the returned query_id, so any claim can be re-run.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd

import config
from ledgerlens.models import Cohort, Window, canonical_cohort_key, cohort_predicate

SCHEMA = """
CREATE TABLE IF NOT EXISTS fact_metric (
  date DATE, metric_name VARCHAR, region VARCHAR, segment VARCHAR,
  payment_rail VARCHAR, product VARCHAR, value DOUBLE
);
CREATE TABLE IF NOT EXISTS dim_registry (dimension VARCHAR, value VARCHAR);
CREATE TABLE IF NOT EXISTS change_event (
  event_id VARCHAR PRIMARY KEY, event_type VARCHAR, ts_start TIMESTAMP, ts_end TIMESTAMP,
  source VARCHAR, blast_radius JSON, description VARCHAR, evidence_refs JSON,
  extraction VARCHAR, confidence DOUBLE
);
CREATE TABLE IF NOT EXISTS ticket (
  ticket_id VARCHAR PRIMARY KEY, created_at TIMESTAMP, account_id VARCHAR,
  region VARCHAR, segment VARCHAR, subject VARCHAR, body VARCHAR, error_code VARCHAR
);
CREATE TABLE IF NOT EXISTS symptom_cluster (
  cluster_id VARCHAR PRIMARY KEY, key VARCHAR, cohort JSON, first_seen DATE,
  volume INTEGER, baseline_volume DOUBLE, lift DOUBLE, sample_refs JSON
);
CREATE TABLE IF NOT EXISTS query_log (
  query_id VARCHAR PRIMARY KEY, sql VARCHAR, params JSON,
  result_preview VARCHAR, executed_at TIMESTAMP, label VARCHAR
);
CREATE TABLE IF NOT EXISTS diagnosis (
  diagnosis_id VARCHAR PRIMARY KEY, anomaly_id VARCHAR, card JSON, created_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS verdict (
  verdict_id VARCHAR PRIMARY KEY, anomaly_id VARCHAR, hypothesis_id VARCHAR,
  event_type VARCHAR, metric VARCHAR, verdict VARCHAR, corrected_cause VARCHAR, ts TIMESTAMP
);
"""


class Store:
    def __init__(self, path: Path | str = config.DB_PATH, read_only: bool = False) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(self.path), read_only=read_only)
        # Two plain dict caches. Not lru_cache: `self` and dict-typed cohorts are
        # unhashable, and the naive attempt is a 20-minute detour (spec 16 #7).
        self._q_cache: dict[str, tuple[pd.DataFrame, str]] = {}
        self._series_cache: dict[tuple, tuple[pd.Series, str]] = {}

    # ------------------------------------------------------------------ schema

    def init_schema(self) -> None:
        self.con.execute(SCHEMA)

    def reset(self) -> None:
        for table in (
            "fact_metric",
            "dim_registry",
            "change_event",
            "ticket",
            "symptom_cluster",
            "query_log",
        ):
            self.con.execute(f"DELETE FROM {table}")
        self._q_cache.clear()
        self._series_cache.clear()

    # ----------------------------------------------------------------- queries

    def q(self, sql: str, params: dict | None = None, label: str = "") -> tuple[pd.DataFrame, str]:
        """Execute, log to query_log, return (df, query_id)."""
        params = params or {}
        payload = sql + json.dumps(params, sort_keys=True, default=str)
        query_id = "q_" + hashlib.sha1(payload.encode()).hexdigest()[:10]
        if query_id in self._q_cache:
            return self._q_cache[query_id]

        df = self.con.execute(sql, params).df()
        preview = self._preview(df)
        # INSERT OR REPLACE, not INSERT: query_id is a primary key and the
        # drill-down legitimately re-issues identical queries across nodes.
        self.con.execute(
            "INSERT OR REPLACE INTO query_log VALUES ($qid, $sql, $params, $preview, $ts, $label)",
            {
                "qid": query_id,
                "sql": sql,
                "params": json.dumps(params, sort_keys=True, default=str),
                "preview": preview,
                "ts": datetime.now(),
                "label": label,
            },
        )
        self._q_cache[query_id] = (df, query_id)
        return df, query_id

    @staticmethod
    def _preview(df: pd.DataFrame) -> str:
        """Byte-stable preview: the acceptance test re-executes logged SQL and
        compares against this string, so it must not carry a timestamp or any
        float formatting that varies with pandas display options."""
        return df.head(3).to_csv(index=False, float_format="%.6f")[:500]

    def replay(self, query_id: str) -> tuple[str, str, str]:
        """Return (sql, stored_preview, freshly_computed_preview) for provenance checks."""
        row = self.con.execute(
            "SELECT sql, params, result_preview FROM query_log WHERE query_id = $qid",
            {"qid": query_id},
        ).fetchone()
        if row is None:
            raise KeyError(f"query_id {query_id} not in query_log")
        sql, params_json, stored = row
        df = self.con.execute(sql, json.loads(params_json)).df()
        return sql, stored, self._preview(df)

    def query_row(self, query_id: str) -> dict | None:
        row = self.con.execute(
            "SELECT query_id, sql, params, result_preview, label FROM query_log WHERE query_id = $q",
            {"q": query_id},
        ).fetchone()
        if row is None:
            return None
        return dict(zip(["query_id", "sql", "params", "result_preview", "label"], row))

    # -------------------------------------------------------------- accessors

    def series(
        self, metric: str, cohort: Cohort, start: date, end: date
    ) -> tuple[pd.Series, str]:
        """Daily summed series for a cohort, reindexed to a gapless daily range."""
        key = (metric, canonical_cohort_key(cohort), start.isoformat(), end.isoformat())
        if key in self._series_cache:
            return self._series_cache[key]

        sql = (
            "SELECT date, SUM(value) AS value FROM fact_metric "
            f"WHERE metric_name = $metric AND date BETWEEN $start AND $end "
            f"AND {cohort_predicate(cohort)} GROUP BY date ORDER BY date"
        )
        df, query_id = self.q(
            sql,
            {"metric": metric, "start": start, "end": end},
            label=f"{metric} daily series",
        )
        if df.empty:
            s = pd.Series(dtype="float64")
        else:
            s = pd.Series(df["value"].to_numpy(dtype="float64"), index=pd.to_datetime(df["date"]))
            s = s.reindex(pd.date_range(start, end, freq="D"))
        self._series_cache[key] = (s, query_id)
        return s, query_id

    def cohort_rows(self, cohort: Cohort, window: Window, metric: str) -> tuple[int, str]:
        """Row count in fact_metric for THE METRIC UNDER INVESTIGATION.

        The metric filter is mandatory (spec 16 #2): without it a blast radius that
        is unconstrained on metric gets its |B| inflated by the other metric's rows
        and the Jaccard comparison in the C component silently breaks.
        """
        sql = (
            "SELECT count(*) AS n FROM fact_metric "
            f"WHERE metric_name = $metric AND date BETWEEN $start AND $end "
            f"AND {cohort_predicate(cohort)}"
        )
        df, query_id = self.q(
            sql,
            {"metric": metric, "start": window.start, "end": window.end},
            label="cohort row count",
        )
        return int(df["n"].iloc[0]), query_id

    def dim_universe(self, dim: str) -> list[str]:
        rows = self.con.execute(
            "SELECT DISTINCT value FROM dim_registry WHERE dimension = $d ORDER BY value",
            {"d": dim},
        ).fetchall()
        return [r[0] for r in rows]

    def dim_registry(self) -> dict[str, list[str]]:
        rows = self.con.execute(
            "SELECT dimension, value FROM dim_registry ORDER BY dimension, value"
        ).fetchall()
        out: dict[str, list[str]] = {}
        for dim, value in rows:
            out.setdefault(dim, []).append(value)
        return out

    def max_date(self, metric: str) -> date:
        row = self.con.execute(
            "SELECT max(date) FROM fact_metric WHERE metric_name = $m", {"m": metric}
        ).fetchone()
        return row[0]

    # ------------------------------------------------------------------- load

    def load_all(self, data_dir: Path | str = config.DATA_DIR) -> None:
        data_dir = Path(data_dir)
        self.init_schema()
        self.reset()

        self.con.execute(
            "INSERT INTO fact_metric SELECT date, metric_name, region, segment, "
            "payment_rail, product, value FROM read_parquet($p)",
            {"p": str(data_dir / "metrics.parquet")},
        )

        rows = [(dim, v) for dim, values in config.DIMENSIONS.items() for v in values]
        self.con.executemany("INSERT INTO dim_registry VALUES (?, ?)", rows)

        from ledgerlens.ledger import connectors

        events = connectors.load_all(data_dir)
        self.con.executemany(
            "INSERT OR REPLACE INTO change_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    e.event_id,
                    e.event_type,
                    e.ts_start,
                    e.ts_end,
                    e.source,
                    json.dumps(e.blast_radius),
                    e.description,
                    json.dumps(e.evidence_refs),
                    e.extraction,
                    e.confidence,
                )
                for e in events
            ],
        )

        tickets = json.loads((data_dir / "tickets.json").read_text())
        self.con.executemany(
            "INSERT OR REPLACE INTO ticket VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    t["ticket_id"],
                    datetime.fromisoformat(t["created_at"]),
                    t["account_id"],
                    t["region"],
                    t["segment"],
                    t["subject"],
                    t["body"],
                    t["error_code"],
                )
                for t in tickets
            ],
        )

    def events(self) -> list:
        from ledgerlens.models import ChangeEvent

        rows = self.con.execute(
            "SELECT event_id, event_type, ts_start, ts_end, source, blast_radius, "
            "description, evidence_refs, extraction, confidence FROM change_event "
            "ORDER BY ts_start, event_id"
        ).fetchall()
        return [
            ChangeEvent(
                event_id=r[0],
                event_type=r[1],
                ts_start=r[2],
                ts_end=r[3],
                source=r[4],
                blast_radius=json.loads(r[5]),
                description=r[6],
                evidence_refs=json.loads(r[7]),
                extraction=r[8],
                confidence=r[9],
            )
            for r in rows
        ]

    def close(self) -> None:
        self.con.close()
