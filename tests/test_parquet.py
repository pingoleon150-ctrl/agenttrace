import pytest

duckdb = pytest.importorskip("duckdb")

from agenttrace.models import Observation, Provenance
from agenttrace.storage.parquet import write_observation_parquet


def test_parquet_round_trip(tmp_path):
    item = Observation(
        source="test",
        source_event_id="1",
        observed_at="2026-01-01T00:00:00Z",
        event_time="2026-01-01T00:00:00Z",
        actor="worker",
        event_type="PushEvent",
        repository="org/repo",
        text="Update shard",
        provenance=Provenance(url="https://example.invalid/1"),
    )
    path = write_observation_parquet(tmp_path / "events.parquet", [item])
    row = duckdb.connect(":memory:").execute(
        "SELECT source_event_id, repository FROM read_parquet(?)", [str(path)]
    ).fetchone()
    assert row == ("1", "org/repo")
