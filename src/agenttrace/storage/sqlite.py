from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Self

from agenttrace.models import EvidenceBundle, Observation

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS observations (
    source TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    event_time TEXT NOT NULL,
    actor TEXT NOT NULL,
    repository TEXT,
    thread_id TEXT,
    content_sha256 TEXT,
    json TEXT NOT NULL,
    PRIMARY KEY (source, source_event_id)
);
CREATE INDEX IF NOT EXISTS idx_observations_time ON observations(event_time);
CREATE INDEX IF NOT EXISTS idx_observations_actor ON observations(actor);
CREATE INDEX IF NOT EXISTS idx_observations_repo ON observations(repository);
CREATE TABLE IF NOT EXISTS evidence_bundles (
    cluster_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    score REAL NOT NULL,
    reviewable INTEGER NOT NULL,
    json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS discovery_fingerprints (
    fingerprint TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS monitor_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    reviewed_at TEXT,
    summary TEXT NOT NULL,
    json TEXT NOT NULL
);
"""


class SQLiteStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def upsert_observation(self, observation: Observation) -> None:
        self.conn.execute(
            """
            INSERT INTO observations(source, source_event_id, event_time, actor, repository, thread_id, content_sha256, json)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(source, source_event_id) DO UPDATE SET
              event_time=excluded.event_time,
              actor=excluded.actor,
              repository=excluded.repository,
              thread_id=excluded.thread_id,
              content_sha256=excluded.content_sha256,
              json=excluded.json
            """,
            (
                observation.source,
                observation.source_event_id,
                observation.event_time.isoformat(),
                observation.actor,
                observation.repository,
                observation.thread_id,
                observation.content_sha256,
                observation.model_dump_json(),
            ),
        )
        self.conn.commit()

    def save_bundle(self, bundle: EvidenceBundle) -> None:
        self.conn.execute(
            """
            INSERT INTO evidence_bundles(cluster_id, created_at, score, reviewable, json)
            VALUES(?,?,?,?,?)
            ON CONFLICT(cluster_id) DO UPDATE SET
              created_at=excluded.created_at,
              score=excluded.score,
              reviewable=excluded.reviewable,
              json=excluded.json
            """,
            (
                bundle.cluster_id,
                bundle.created_at.isoformat(),
                bundle.score.score,
                int(bundle.score.reviewable),
                bundle.model_dump_json(),
            ),
        )
        self.conn.commit()

    def list_observations(self, limit: int = 10000) -> list[Observation]:
        rows = self.conn.execute(
            "SELECT json FROM observations ORDER BY event_time DESC LIMIT ?", (limit,)
        ).fetchall()
        return [Observation.model_validate_json(row[0]) for row in rows]

    def claim_fingerprint(self, fingerprint: str, first_seen: str) -> bool:
        cursor = self.conn.execute(
            "INSERT OR IGNORE INTO discovery_fingerprints(fingerprint, first_seen) VALUES(?,?)",
            (fingerprint, first_seen),
        )
        self.conn.commit()
        return cursor.rowcount == 1

    def observations_for_repositories(
        self, repositories: set[str], limit: int = 10000
    ) -> list[Observation]:
        if not repositories:
            return []
        placeholders = ",".join("?" for _ in repositories)
        rows = self.conn.execute(
            f"SELECT json FROM observations WHERE repository IN ({placeholders}) "
            "ORDER BY event_time DESC LIMIT ?",
            (*sorted(repositories), limit),
        ).fetchall()
        return [Observation.model_validate_json(row[0]) for row in rows]

    def pending_alert(self) -> dict | None:
        row = self.conn.execute(
            "SELECT id, status, summary, json FROM monitor_alerts "
            "WHERE status='pending' ORDER BY id LIMIT 1"
        ).fetchone()
        return (
            None
            if row is None
            else {"id": row[0], "status": row[1], "summary": row[2], "json": row[3]}
        )

    def create_alert(self, fingerprint: str, summary: str, bundle: EvidenceBundle) -> int:
        self.conn.execute(
            "INSERT OR IGNORE INTO monitor_alerts(fingerprint, created_at, summary, json) VALUES(?,?,?,?)",
            (fingerprint, bundle.created_at.isoformat(), summary, bundle.model_dump_json()),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT id FROM monitor_alerts WHERE fingerprint=?", (fingerprint,)
        ).fetchone()
        return int(row[0])

    def resolve_alert(self, alert_id: int, status: str, reviewed_at: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE monitor_alerts SET status=?, reviewed_at=? WHERE id=? AND status='pending'",
            (status, reviewed_at, alert_id),
        )
        self.conn.commit()
        return cursor.rowcount == 1
