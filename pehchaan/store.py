"""The identity store: an OLTP database with full history ("time travel").

Key idea: we never UPDATE or DELETE an assignment. When a record moves to a different
identity (because two identities merged), we CLOSE the old row by setting valid_to,
and INSERT a new row with valid_from. This is a Slowly Changing Dimension, Type 2.

That lets us answer "what did we believe on 1 March?" with one query:
    valid_from <= '2026-03-01' AND (valid_to IS NULL OR valid_to > '2026-03-01')

Works with SQLite (local runs, tests) and PostgreSQL (Docker). SQL is written with '?'
placeholders and converted to '%s' for PostgreSQL.
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from pehchaan.config import DB_URL
from pehchaan.matching import MatchResult
from pehchaan.normalize import NormRecord
from pehchaan.phonetic import indic_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    record_id    VARCHAR(40) PRIMARY KEY,
    source       VARCHAR(20) NOT NULL,
    ingested_at  {ts} NOT NULL,
    norm_json    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS record_attributes (
    record_id  VARCHAR(40) NOT NULL,
    kind       VARCHAR(10) NOT NULL,
    value      VARCHAR(200) NOT NULL,
    PRIMARY KEY (record_id, kind, value)
);
CREATE INDEX IF NOT EXISTS idx_attr_lookup ON record_attributes (kind, value);
CREATE TABLE IF NOT EXISTS identities (
    identity_id  VARCHAR(20) PRIMARY KEY,
    created_at   {ts} NOT NULL,
    merged_into  VARCHAR(20),
    merged_at    {ts}
);
CREATE TABLE IF NOT EXISTS assignments (
    record_id    VARCHAR(40) NOT NULL,
    identity_id  VARCHAR(20) NOT NULL,
    valid_from   {ts} NOT NULL,
    valid_to     {ts},
    reason       TEXT,
    PRIMARY KEY (record_id, valid_from, identity_id)
);
CREATE INDEX IF NOT EXISTS idx_assign_identity ON assignments (identity_id);
CREATE INDEX IF NOT EXISTS idx_assign_record ON assignments (record_id);
CREATE TABLE IF NOT EXISTS links (
    record_a    VARCHAR(40) NOT NULL,
    record_b    VARCHAR(40) NOT NULL,
    score       DOUBLE PRECISION NOT NULL,
    reasons     TEXT NOT NULL,
    created_at  {ts} NOT NULL,
    PRIMARY KEY (record_a, record_b)
);
CREATE TABLE IF NOT EXISTS ring_reports (
    run_id        VARCHAR(40) NOT NULL,
    component_id  INTEGER NOT NULL,
    label         VARCHAR(20) NOT NULL,
    risk_score    DOUBLE PRECISION NOT NULL,
    identity_ids  TEXT NOT NULL,
    features      TEXT NOT NULL,
    reasons       TEXT NOT NULL,
    created_at    {ts} NOT NULL,
    PRIMARY KEY (run_id, component_id)
);
CREATE TABLE IF NOT EXISTS ring_reviews (
    run_id        VARCHAR(40) NOT NULL,
    component_id  INTEGER NOT NULL,
    decision      VARCHAR(20) NOT NULL,
    note          TEXT,
    reviewed_at   {ts} NOT NULL,
    PRIMARY KEY (run_id, component_id)
);
"""


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


class Store:
    def __init__(self, url: str = DB_URL):
        if url.startswith("sqlite:///"):
            path = url[len("sqlite:///"):]
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            # FastAPI handles requests in worker threads; SQLite connections must allow
            # cross-thread access for the same store instance during request processing.
            self.conn = sqlite3.connect(path, check_same_thread=False)
            self.dialect = "sqlite"
        elif url.startswith("postgresql"):
            import psycopg2  # only needed when using PostgreSQL
            self.conn = psycopg2.connect(url)
            self.dialect = "postgresql"
        else:
            raise ValueError(f"Unsupported database URL: {url}")

    # ---------- low-level helpers ----------
    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.dialect == "postgresql" else sql

    def execute(self, sql: str, params: tuple = ()) -> None:
        cur = self.conn.cursor()
        cur.execute(self._sql(sql), params)
        cur.close()

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(self._sql(sql), params)
        cols = [c[0] for c in cur.description]
        rows = [{c: _iso(v) for c, v in zip(cols, row)} for row in cur.fetchall()]
        cur.close()
        return rows

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        ts = "TEXT" if self.dialect == "sqlite" else "TIMESTAMP"
        for statement in SCHEMA.format(ts=ts).split(";"):
            if statement.strip():
                self.execute(statement)
        self.commit()

    # ---------- write side (used by the resolver) ----------
    def has_record(self, record_id: str) -> bool:
        return bool(self.query("SELECT 1 AS x FROM records WHERE record_id = ?", (record_id,)))

    def save_record(self, r: NormRecord) -> None:
        self.execute("INSERT INTO records (record_id, source, ingested_at, norm_json) VALUES (?, ?, ?, ?)",
                     (r.record_id, r.source, r.ingested_at, json.dumps(r.to_dict())))
        attributes = [("phone", p) for p in r.phones]
        attributes += [(k, v) for k, v in (("email", r.email), ("device", r.device_id),
                                           ("address", r.address), ("id", r.id_hash)) if v]
        # phonetic keys of name tokens: lets the console find 'Laxmi' when you search 'Lakshmi'
        attributes += [("nkey", k) for k in {indic_key(t) for t in r.name_tokens if len(t) > 1} if k]
        for kind, value in attributes:
            self.execute("INSERT INTO record_attributes (record_id, kind, value) VALUES (?, ?, ?) "
                         "ON CONFLICT DO NOTHING", (r.record_id, kind, value))

    def create_identity(self, identity_id: str, at: str) -> None:
        self.execute("INSERT INTO identities (identity_id, created_at) VALUES (?, ?)", (identity_id, at))

    def assign(self, record_id: str, identity_id: str, at: str, reason: str) -> None:
        # Kafka does not guarantee time order across topics. If this event is older than
        # the record's current assignment, use the later time so a history row never
        # ends before it starts.
        current = self.query("SELECT valid_from FROM assignments WHERE record_id = ? AND valid_to IS NULL",
                             (record_id,))
        if current and str(current[0]["valid_from"]) > at:
            at = str(current[0]["valid_from"])
        self.execute("UPDATE assignments SET valid_to = ? WHERE record_id = ? AND valid_to IS NULL",
                     (at, record_id))
        self.execute("INSERT INTO assignments (record_id, identity_id, valid_from, reason) VALUES (?, ?, ?, ?)",
                     (record_id, identity_id, at, reason))

    def merge_identity(self, absorbed: str, survivor: str, at: str) -> None:
        """Move every current record of `absorbed` into `survivor`, keeping history."""
        rows = self.query("SELECT record_id FROM assignments WHERE identity_id = ? AND valid_to IS NULL",
                          (absorbed,))
        for row in rows:
            self.assign(row["record_id"], survivor, at, f"merged from {absorbed}")
        self.execute("UPDATE identities SET merged_into = ?, merged_at = ? WHERE identity_id = ?",
                     (survivor, at, absorbed))

    def add_link(self, record_a: str, record_b: str, result: MatchResult, at: str) -> None:
        self.execute("INSERT INTO links (record_a, record_b, score, reasons, created_at) "
                     "VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                     (record_a, record_b, result.score, json.dumps(result.reasons), at))

    def max_identity_number(self) -> int:
        rows = self.query("SELECT identity_id FROM identities")
        return max((int(r["identity_id"][3:]) for r in rows), default=0)

    def load_state(self) -> list[tuple[NormRecord, str]]:
        """All records with their CURRENT identity, used to rebuild memory on restart."""
        rows = self.query(
            "SELECT r.norm_json, a.identity_id FROM records r "
            "JOIN assignments a ON a.record_id = r.record_id AND a.valid_to IS NULL "
            "ORDER BY r.ingested_at")
        return [(NormRecord.from_dict(json.loads(r["norm_json"])), r["identity_id"]) for r in rows]

    # ---------- read side (used by the API and the analysis job) ----------
    @staticmethod
    def _as_of_clause(as_of: str | None) -> tuple[str, tuple]:
        if as_of is None:
            return "a.valid_to IS NULL", ()
        return "a.valid_from <= ? AND (a.valid_to IS NULL OR a.valid_to > ?)", (as_of, as_of)

    def identity_of_record(self, record_id: str, as_of: str | None = None) -> str | None:
        clause, params = self._as_of_clause(as_of)
        rows = self.query(f"SELECT a.identity_id FROM assignments a WHERE a.record_id = ? AND {clause}",
                          (record_id, *params))
        return rows[0]["identity_id"] if rows else None

    def identity_records(self, identity_id: str, as_of: str | None = None) -> list[dict]:
        clause, params = self._as_of_clause(as_of)
        rows = self.query(
            f"SELECT r.record_id, r.source, r.ingested_at, r.norm_json, a.valid_from, a.reason "
            f"FROM assignments a JOIN records r ON r.record_id = a.record_id "
            f"WHERE a.identity_id = ? AND {clause} ORDER BY r.ingested_at",
            (identity_id, *params))
        for row in rows:
            row["norm"] = json.loads(row.pop("norm_json"))
        return rows

    def identity_info(self, identity_id: str) -> dict | None:
        rows = self.query("SELECT * FROM identities WHERE identity_id = ?", (identity_id,))
        return rows[0] if rows else None

    def identity_history(self, identity_id: str) -> list[dict]:
        return self.query(
            "SELECT record_id, valid_from, valid_to, reason FROM assignments "
            "WHERE identity_id = ? ORDER BY valid_from, record_id", (identity_id,))

    def links_between(self, record_ids: list[str]) -> list[dict]:
        if not record_ids:
            return []
        marks = ",".join("?" for _ in record_ids)
        rows = self.query(f"SELECT * FROM links WHERE record_a IN ({marks}) AND record_b IN ({marks}) "
                          f"ORDER BY created_at", (*record_ids, *record_ids))
        for row in rows:
            row["reasons"] = json.loads(row["reasons"])
        return rows

    def records_with_attribute(self, kind: str, value: str) -> list[str]:
        return [r["record_id"] for r in self.query(
            "SELECT record_id FROM record_attributes WHERE kind = ? AND value = ?", (kind, value))]

    def current_assignments(self) -> dict[str, str]:
        return {r["record_id"]: r["identity_id"] for r in self.query(
            "SELECT record_id, identity_id FROM assignments WHERE valid_to IS NULL")}

    def current_identity_attributes(self) -> list[dict]:
        return self.query(
            "SELECT a.identity_id, r.record_id, r.source, r.ingested_at, ra.kind, ra.value "
            "FROM assignments a JOIN records r ON r.record_id = a.record_id "
            "LEFT JOIN record_attributes ra ON ra.record_id = r.record_id "
            "WHERE a.valid_to IS NULL")

    def records_matching_name_keys(self, keys: list[str]) -> list[str]:
        """Records whose name contains ALL of these phonetic keys."""
        if not keys:
            return []
        marks = ",".join("?" for _ in keys)
        return [r["record_id"] for r in self.query(
            f"SELECT record_id FROM record_attributes WHERE kind = 'nkey' AND value IN ({marks}) "
            f"GROUP BY record_id HAVING COUNT(DISTINCT value) = ?", (*keys, len(set(keys))))]

    def attributes_for_identities(self, identity_ids: list[str]) -> list[dict]:
        if not identity_ids:
            return []
        marks = ",".join("?" for _ in identity_ids)
        return self.query(
            f"SELECT a.identity_id, ra.kind, ra.value FROM assignments a "
            f"JOIN record_attributes ra ON ra.record_id = a.record_id "
            f"WHERE a.valid_to IS NULL AND a.identity_id IN ({marks}) "
            f"AND ra.kind IN ('phone', 'device', 'address')", tuple(identity_ids))

    def recent_merges(self, limit: int) -> list[dict]:
        return self.query("SELECT identity_id, merged_into, merged_at FROM identities "
                          "WHERE merged_into IS NOT NULL ORDER BY merged_at DESC LIMIT ?", (limit,))

    def recent_records(self, limit: int) -> list[dict]:
        rows = self.query(
            "SELECT r.record_id, r.source, r.ingested_at, r.norm_json, a.identity_id, a.reason "
            "FROM records r JOIN assignments a ON a.record_id = r.record_id AND a.valid_to IS NULL "
            "ORDER BY r.ingested_at DESC LIMIT ?", (limit,))
        for row in rows:
            row["norm"] = json.loads(row.pop("norm_json"))
        return rows

    def save_review(self, run_id: str, component_id: int, decision: str, note: str, at: str) -> None:
        self.execute("DELETE FROM ring_reviews WHERE run_id = ? AND component_id = ?", (run_id, component_id))
        self.execute("INSERT INTO ring_reviews (run_id, component_id, decision, note, reviewed_at) "
                     "VALUES (?, ?, ?, ?, ?)", (run_id, component_id, decision, note, at))
        self.commit()

    def reviews_for_run(self, run_id: str) -> dict[int, dict]:
        return {int(r["component_id"]): r for r in self.query(
            "SELECT * FROM ring_reviews WHERE run_id = ?", (run_id,))}

    def ring_component(self, run_id: str, component_id: int) -> dict | None:
        rows = self.query("SELECT * FROM ring_reports WHERE run_id = ? AND component_id = ?",
                          (run_id, component_id))
        if not rows:
            return None
        row = rows[0]
        for col in ("identity_ids", "features", "reasons"):
            row[col] = json.loads(row[col])
        return row

    def stats(self) -> dict:
        one = lambda sql: self.query(sql)[0]["n"]
        return {
            "records": one("SELECT COUNT(*) AS n FROM records"),
            "identities_active": one("SELECT COUNT(*) AS n FROM identities WHERE merged_into IS NULL"),
            "identities_merged_away": one("SELECT COUNT(*) AS n FROM identities WHERE merged_into IS NOT NULL"),
            "links": one("SELECT COUNT(*) AS n FROM links"),
            "records_by_source": {r["source"]: r["n"] for r in self.query(
                "SELECT source, COUNT(*) AS n FROM records GROUP BY source")},
            "latest_ingested_at": self.query("SELECT MAX(ingested_at) AS n FROM records")[0]["n"],
        }

    def save_ring_report(self, run_id: str, rows: list[dict], at: str) -> None:
        for r in rows:
            self.execute(
                "INSERT INTO ring_reports (run_id, component_id, label, risk_score, identity_ids, "
                "features, reasons, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, r["component_id"], r["label"], r["risk_score"], json.dumps(r["identity_ids"]),
                 json.dumps(r["features"]), json.dumps(r["reasons"]), at))
        self.commit()

    def latest_ring_report(self) -> list[dict]:
        latest = self.query("SELECT run_id FROM ring_reports ORDER BY created_at DESC LIMIT 1")
        if not latest:
            return []
        rows = self.query("SELECT * FROM ring_reports WHERE run_id = ? ORDER BY risk_score DESC, component_id",
                          (latest[0]["run_id"],))
        for row in rows:
            for col in ("identity_ids", "features", "reasons"):
                row[col] = json.loads(row[col])
        return rows
