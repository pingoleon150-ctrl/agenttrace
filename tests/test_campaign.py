import asyncio
from datetime import UTC, datetime

import httpx

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


class FailingCollector(Collector):
    async def collect(self):
        request = httpx.Request("GET", "https://example.test/search")
        response = httpx.Response(429, request=request)
        raise httpx.HTTPStatusError("limited", request=request, response=response)
        yield  # pragma: no cover


class ExhaustedCollector(Collector):
    exhausted = True

    async def collect(self):
        if False:
            yield


def test_load_queries_deduplicates(tmp_path):
    path = tmp_path / "queries.yaml"
    path.write_text('families:\n  one: ["alpha", "beta"]\n  two: ["alpha"]\n')
    assert load_queries(path) == ["alpha", "beta"]


def test_campaign_deduplicates_across_sources(tmp_path):
    factories = {
        "first": lambda query, page: FakeCollector("first", query),
        "second": lambda query, page: FakeCollector("second", query),
    }
    with SQLiteStore(tmp_path / "campaign.db") as store:
        result = asyncio.run(run_campaign(["needle"], factories, store))
        repeated = asyncio.run(run_campaign(["needle"], factories, store))
        stored = store.list_observations()

    assert len(result.observations) == 1
    assert repeated.observations == []
    assert len(stored) == 1
    assert stored[0].source == "campaign"
    assert stored[0].metadata["campaign_query"] == "needle"
    assert stored[0].metadata["origin_source"] == "first"


def test_alert_pauses_until_resolved(tmp_path):
    factories = {"first": lambda query, page: FakeCollector("first", query)}
    with SQLiteStore(tmp_path / "alerts.db") as store:
        result = asyncio.run(run_campaign(["needle"], factories, store))
        alert_id = store.create_alert("candidate-1", "summary", result.bundles[0])
        assert store.pending_alert()["id"] == alert_id
        assert store.resolve_alert(alert_id, "reviewed", "2026-08-17T00:00:00+00:00")
        assert store.pending_alert() is None


def test_query_and_page_rotation_persist(tmp_path):
    with SQLiteStore(tmp_path / "rotation.db") as store:
        assert store.take_query_batch(["one", "two", "three"], 2) == ["one", "two"]
        assert store.take_query_batch(["one", "two", "three"], 2) == ["three", "one"]

        assert store.discovery_page("github-code", "one", 3) == 1
        store.advance_discovery_page(
            "github-code", "one", current_page=1, max_page=3, updated_at="now"
        )
        assert store.discovery_page("github-code", "one", 3) == 2
        store.advance_discovery_page(
            "github-code", "one", current_page=2, max_page=3, updated_at="later", step=2
        )
        assert store.discovery_page("github-code", "one", 3) == 1


def test_campaign_advances_only_successful_source_pages(tmp_path):
    factories = {"first": lambda query, page: FakeCollector("first", f"{query}-{page}")}
    with SQLiteStore(tmp_path / "pages.db") as store:
        first = asyncio.run(
            run_campaign(
                ["needle"],
                factories,
                store,
                rotate_pages=True,
                page_limits={"first": 3},
            )
        )
        second = asyncio.run(
            run_campaign(
                ["needle"],
                factories,
                store,
                rotate_pages=True,
                page_limits={"first": 3},
            )
        )

    assert first.search_pages[0]["page"] == 1
    assert second.search_pages[0]["page"] == 2


def test_campaign_does_not_advance_failed_source_page(tmp_path):
    factories = {"limited": lambda query, page: FailingCollector()}
    with SQLiteStore(tmp_path / "failed-pages.db") as store:
        result = asyncio.run(
            run_campaign(
                ["needle"],
                factories,
                store,
                retries=0,
                rotate_pages=True,
                page_limits={"limited": 3},
            )
        )
        page = store.discovery_page("limited", "needle", 3)

    assert result.errors
    assert page == 1


def test_campaign_resets_exhausted_source_to_page_one(tmp_path):
    factories = {"finite": lambda query, page: ExhaustedCollector()}
    with SQLiteStore(tmp_path / "exhausted-pages.db") as store:
        store.advance_discovery_page(
            "finite", "needle", current_page=1, max_page=5, updated_at="before"
        )
        result = asyncio.run(
            run_campaign(
                ["needle"],
                factories,
                store,
                rotate_pages=True,
                page_limits={"finite": 5},
            )
        )
        page = store.discovery_page("finite", "needle", 5)

    assert result.search_pages[0]["page"] == 2
    assert page == 1
