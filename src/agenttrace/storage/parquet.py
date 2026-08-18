from __future__ import annotations

import json
from pathlib import Path

from agenttrace.models import Observation


def write_observation_parquet(path: str | Path, observations: list[Observation]) -> Path:
    """Write a columnar candidate lake while SQLite retains state and evidence."""
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - depends on optional installation
        raise RuntimeError("Parquet export requires: pip install 'agenttrace[archive]'") from exc

    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        (
            item.event_key,
            item.source,
            item.source_event_id,
            item.platform,
            item.event_time,
            item.actor_key,
            item.event_type,
            item.repository,
            item.conversation_key,
            item.text,
            item.content_sha256,
            json.dumps(item.metadata, sort_keys=True, default=str),
            item.provenance.url,
        )
        for item in observations
    ]
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE observations (
                event_key VARCHAR, source VARCHAR, source_event_id VARCHAR,
                platform VARCHAR, event_time TIMESTAMPTZ, actor_key VARCHAR,
                event_type VARCHAR, repository VARCHAR, conversation_key VARCHAR,
                text VARCHAR, content_sha256 VARCHAR, metadata_json VARCHAR,
                provenance_url VARCHAR
            )
            """
        )
        if rows:
            connection.executemany(
                "INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
            )
        escaped = str(target).replace("'", "''")
        connection.execute(
            f"COPY observations TO '{escaped}' (FORMAT parquet, COMPRESSION zstd)"
        )
    finally:
        connection.close()
    return target
