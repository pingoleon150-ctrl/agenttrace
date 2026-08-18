from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Self

from agenttrace.models import EvidenceBundle, Observation

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS observations (
    event_key TEXT NOT NULL PRIMARY KEY,
    source TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    event_time TEXT NOT NULL,
    actor TEXT NOT NULL,
    repository TEXT,
    thread_id TEXT,
    content_sha256 TEXT,
    json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_observations_time ON observations(event_time);
CREATE INDEX IF NOT EXISTS idx_observations_actor ON observations(actor);
CREATE INDEX IF NOT EXISTS idx_observations_repo ON observations(repository);
CREATE INDEX IF NOT EXISTS idx_observations_source_time ON observations(source, event_time);
CREATE INDEX IF NOT EXISTS idx_observations_source_event
ON observations(source, source_event_id);
CREATE INDEX IF NOT EXISTS idx_observations_thread_time
ON observations(repository, thread_id, event_time);
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
CREATE TABLE IF NOT EXISTS discovery_cursors (
    source TEXT NOT NULL,
    query TEXT NOT NULL,
    next_page INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source, query)
);
CREATE TABLE IF NOT EXISTS discovery_cursor_state (
    source TEXT NOT NULL,
    query TEXT NOT NULL,
    cursor_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source, query)
);
CREATE TABLE IF NOT EXISTS monitor_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ingestion_partitions (
    source TEXT NOT NULL,
    partition_key TEXT NOT NULL,
    status TEXT NOT NULL,
    cursor TEXT,
    stats_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    error TEXT,
    PRIMARY KEY (source, partition_key)
);
"""


class SQLiteStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._migrate_observation_key()
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def upsert_observation(self, observation: Observation) -> None:
        self.upsert_observations_batch([observation])

    def upsert_observations_batch(self, observations: list[Observation]) -> None:
        if not observations:
            return
        self.conn.executemany(
            """
            INSERT INTO observations(event_key, source, source_event_id, event_time, actor, repository, thread_id, content_sha256, json)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(event_key) DO UPDATE SET
              source=excluded.source,
              source_event_id=excluded.source_event_id,
              event_time=excluded.event_time,
              actor=excluded.actor,
              repository=excluded.repository,
              thread_id=excluded.thread_id,
              content_sha256=excluded.content_sha256,
              json=excluded.json
            """,
            [
                (
                    observation.event_key,
                    observation.source,
                    observation.source_event_id,
                    observation.event_time.isoformat(),
                    observation.actor,
                    observation.repository,
                    observation.thread_id,
                    observation.content_sha256,
                    observation.model_dump_json(),
                )
                for observation in observations
            ],
        )
        self.conn.commit()

    def _migrate_observation_key(self) -> None:
        """Move legacy source/event primary keys to the canonical platform event key."""
        columns = self.conn.execute("PRAGMA table_info(observations)").fetchall()
        if not columns:
            return
        event_key_column = next((column for column in columns if column[1] == "event_key"), None)
        if event_key_column and event_key_column[5] == 1:
            return

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute("ALTER TABLE observations RENAME TO observations_legacy")
            self.conn.execute(
                """
                CREATE TABLE observations (
                    event_key TEXT NOT NULL PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_event_id TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    repository TEXT,
                    thread_id TEXT,
                    content_sha256 TEXT,
                    json TEXT NOT NULL
                )
                """
            )
            self.conn.execute(
                """
                INSERT INTO observations(
                    event_key, source, source_event_id, event_time, actor,
                    repository, thread_id, content_sha256, json
                )
                SELECT
                    COALESCE(
                        CASE WHEN json_valid(json)
                            THEN NULLIF(json_extract(json, '$.event_key'), '')
                        END,
                        (CASE
                            WHEN lower(source) LIKE '%github%'
                                OR lower(source) IN ('gharchive', 'grepapp')
                            THEN 'github'
                            ELSE lower(source)
                        END) || ':event:' || source || ':' || source_event_id
                    ),
                    source, source_event_id, event_time, actor, repository,
                    thread_id, content_sha256, json
                FROM observations_legacy
                """
            )
            self.conn.execute("DROP TABLE observations_legacy")
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def ingestion_partition(self, source: str, partition_key: str) -> dict | None:
        row = self.conn.execute(
            "SELECT status, cursor, stats_json, updated_at, completed_at, error "
            "FROM ingestion_partitions WHERE source=? AND partition_key=?",
            (source, partition_key),
        ).fetchone()
        if row is None:
            return None
        return {
            "status": row[0],
            "cursor": row[1],
            "stats": json.loads(row[2]),
            "updated_at": row[3],
            "completed_at": row[4],
            "error": row[5],
        }

    def start_ingestion_partition(self, source: str, partition_key: str, updated_at: str) -> None:
        self.conn.execute(
            "INSERT INTO ingestion_partitions(source, partition_key, status, updated_at) "
            "VALUES(?,?, 'running', ?) ON CONFLICT(source, partition_key) DO UPDATE SET "
            "status='running', updated_at=excluded.updated_at, completed_at=NULL, error=NULL",
            (source, partition_key, updated_at),
        )
        self.conn.commit()

    def finish_ingestion_partition(
        self,
        source: str,
        partition_key: str,
        status: str,
        updated_at: str,
        stats: dict,
        error: str | None = None,
    ) -> None:
        completed_at = updated_at if status == "complete" else None
        self.conn.execute(
            "UPDATE ingestion_partitions SET status=?, stats_json=?, updated_at=?, "
            "completed_at=?, error=? WHERE source=? AND partition_key=?",
            (
                status,
                json.dumps(stats, sort_keys=True),
                updated_at,
                completed_at,
                error,
                source,
                partition_key,
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

    def health(self) -> dict[str, Any]:
        counts = {
            table: int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "observations",
                "evidence_bundles",
                "discovery_fingerprints",
                "monitor_alerts",
                "ingestion_partitions",
            )
        }
        event_range = self.conn.execute(
            "SELECT MIN(event_time), MAX(event_time) FROM observations"
        ).fetchone()
        paths = [Path(self.path), Path(f"{self.path}-wal"), Path(f"{self.path}-shm")]
        return {
            "database": self.path,
            "bytes_on_disk": sum(path.stat().st_size for path in paths if path.exists()),
            "counts": counts,
            "oldest_event_time": event_range[0],
            "newest_event_time": event_range[1],
            "pending_alert": self.pending_alert() is not None,
        }

    def claim_fingerprint(self, fingerprint: str, first_seen: str) -> bool:
        cursor = self.conn.execute(
            "INSERT OR IGNORE INTO discovery_fingerprints(fingerprint, first_seen) VALUES(?,?)",
            (fingerprint, first_seen),
        )
        self.conn.commit()
        return cursor.rowcount == 1

    def take_query_batch(self, queries: list[str], batch_size: int) -> list[str]:
        """Return the next circular query batch and persist the following position."""
        if not queries:
            return []
        size = min(len(queries), max(1, batch_size))
        row = self.conn.execute(
            "SELECT value FROM monitor_state WHERE key='query_cursor'"
        ).fetchone()
        start = int(row[0]) % len(queries) if row else 0
        selected = [queries[(start + offset) % len(queries)] for offset in range(size)]
        next_start = (start + size) % len(queries)
        self.conn.execute(
            "INSERT INTO monitor_state(key, value) VALUES('query_cursor', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(next_start),),
        )
        self.conn.commit()
        return selected

    def discovery_page(self, source: str, query: str, max_page: int) -> int:
        generic = self.discovery_cursor(source, query)
        if isinstance(generic, int):
            return generic if 1 <= generic <= max(1, max_page) else 1
        row = self.conn.execute(
            "SELECT next_page FROM discovery_cursors WHERE source=? AND query=?",
            (source, query),
        ).fetchone()
        page = int(row[0]) if row else 1
        return page if 1 <= page <= max(1, max_page) else 1

    def discovery_cursor(self, source: str, query: str, default: Any = None) -> Any:
        """Return an opaque JSON cursor for page, token, timestamp, or offset sources."""
        row = self.conn.execute(
            "SELECT cursor_json FROM discovery_cursor_state WHERE source=? AND query=?",
            (source, query),
        ).fetchone()
        return default if row is None else json.loads(row[0])

    def set_discovery_cursor(
        self, source: str, query: str, cursor: Any, updated_at: str
    ) -> None:
        self.conn.execute(
            "INSERT INTO discovery_cursor_state(source, query, cursor_json, updated_at) "
            "VALUES(?,?,?,?) ON CONFLICT(source, query) DO UPDATE SET "
            "cursor_json=excluded.cursor_json, updated_at=excluded.updated_at",
            (source, query, json.dumps(cursor, sort_keys=True), updated_at),
        )
        self.conn.commit()

    def advance_discovery_page(
        self,
        source: str,
        query: str,
        current_page: int,
        max_page: int,
        updated_at: str,
        step: int = 1,
    ) -> None:
        """Advance after a successful request, wrapping within the source search cap."""
        maximum = max(1, max_page)
        next_page = ((current_page - 1 + max(1, step)) % maximum) + 1
        self.conn.execute(
            "INSERT INTO discovery_cursors(source, query, next_page, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(source, query) DO UPDATE SET "
            "next_page=excluded.next_page, updated_at=excluded.updated_at",
            (source, query, next_page, updated_at),
        )
        self.set_discovery_cursor(source, query, next_page, updated_at)
        self.conn.commit()

    def reset_discovery_page(self, source: str, query: str, updated_at: str) -> None:
        self.conn.execute(
            "INSERT INTO discovery_cursors(source, query, next_page, updated_at) VALUES(?,?,1,?) "
            "ON CONFLICT(source, query) DO UPDATE SET "
            "next_page=1, updated_at=excluded.updated_at",
            (source, query, updated_at),
        )
        self.set_discovery_cursor(source, query, 1, updated_at)
        self.conn.commit()

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
