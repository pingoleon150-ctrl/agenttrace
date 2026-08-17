import asyncio
from datetime import UTC, datetime

from agenttrace.campaign import load_queries, run_campaign
from agenttrace.collectors.base import Collector
from agenttrace.models import Observation, Provenance
from agenttrace.storage.sqlite import SQLiteStore


class FakeCollector(Collector):
    def __init__(self, source: str, query: str):
        self.source = source
        self.query = query

    async def collect(self):
        now = datetime.now(UTC)
        yield Observation(
            source=self.source,
            source_event_id=f"{self.source}-1",
            observed_at=now,
            event_time=now,
            actor="worker-a",
            event_type="post",
            text="TASK-ID: task-1234 ACK heartbeat",
            repository="example/repo",
            thread_id="7",
            content_sha256="same-content",
            provenance=Provenance(url="https://example.test/one"),
        )


def test_load_queries_deduplicates(tmp_path):
    path = tmp_path / "queries.yaml"
    path.write_text('families:\n  one: ["alpha", "beta"]\n  two: ["alpha"]\n')
    assert load_queries(path) == ["alpha", "beta"]


def test_campaign_deduplicates_across_sources(tmp_path):
    factories = {
        "first": lambda query: FakeCollector("first", query),
        "second": lambda query: FakeCollector("second", query),
    }
    with SQLiteStore(tmp_path / "campaign.db") as store:
        result = asyncio.run(run_campaign(["needle"], factories, store))
        stored = store.list_observations()

    assert len(result.observations) == 1
    assert len(stored) == 1
    assert stored[0].source == "campaign"
    assert stored[0].metadata["campaign_query"] == "needle"
    assert stored[0].metadata["origin_source"] == "first"
