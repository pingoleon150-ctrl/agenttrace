import asyncio
import gzip
import json

import httpx
import pytest

from agenttrace.collectors.gharchive import GHArchiveHourCollector
from agenttrace.storage.sqlite import SQLiteStore


def event(event_id: str, text: str, event_type: str = "IssuesEvent") -> dict:
    return {
        "id": event_id,
        "type": event_type,
        "created_at": "2026-08-17T12:00:00+00:00",
        "public": True,
        "actor": {"login": "alice", "type": "User"},
        "repo": {"name": "example/repo"},
        "payload": {
            "action": "opened",
            "issue": {
                "id": int(event_id) if event_id.isdigit() else 1,
                "number": 7,
                "title": text,
                "body": "body",
                "html_url": "https://github.com/example/repo/issues/7",
            },
        },
    }


def collector_for(events: list[dict], **kwargs) -> GHArchiveHourCollector:
    payload = gzip.compress(b"\n".join(json.dumps(item).encode() for item in events) + b"\n")
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=payload))
    return GHArchiveHourCollector("2026-08-17-12", transport=transport, **kwargs)


def issue_comment_event(event_id: str, root_text: str, comment_text: str) -> dict:
    item = event(event_id, root_text, event_type="IssueCommentEvent")
    item["payload"]["comment"] = {
        "id": 99,
        "body": comment_text,
        "html_url": "https://github.com/example/repo/issues/7#issuecomment-99",
    }
    return item


def test_stream_filter_keeps_candidates_and_drops_unsupported_events():
    collector = collector_for(
        [
            event("1", "delegate task_id=alpha-9217"),
            event("2", "ordinary issue"),
            event("3", "checkpoint", event_type="WatchEvent"),
        ],
        sample_rate=0.0,
    )
    observations = asyncio.run(_collect(collector))
    assert [observation.source_event_id for observation in observations] == ["1"]
    assert collector.stats["events_scanned"] == 3
    assert collector.stats["candidate_events"] == 1


def test_sampling_is_deterministic():
    first = GHArchiveHourCollector("2026-08-17-12", sample_rate=0.25)
    second = GHArchiveHourCollector("2026-08-17-12", sample_rate=0.25)
    assert [first._sampled(str(value)) for value in range(50)] == [
        second._sampled(str(value)) for value in range(50)
    ]


def test_archive_hour_normalizes_zero_padded_hours_to_upstream_filename():
    assert GHArchiveHourCollector("2026-08-17-00").hour == "2026-08-17-0"
    assert GHArchiveHourCollector("2026-08-17T09Z").hour == "2026-08-17-9"
    assert GHArchiveHourCollector("2026-08-17-12").hour == "2026-08-17-12"


def test_issue_root_candidate_text_is_not_copied_into_each_comment():
    collector = collector_for(
        [issue_comment_event("1", "delegate task_id=alpha-9217", "ordinary reply")],
        sample_rate=0.0,
    )
    assert asyncio.run(_collect(collector)) == []
    assert collector.stats["candidate_events"] == 0


def test_observation_cap_reserves_capacity_for_late_candidates_and_scans_to_eof():
    collector = collector_for(
        [event("1", "ordinary issue"), event("2", "delegate task_id=alpha-9217")],
        sample_rate=1.0,
        max_observations=1,
    )
    observations = asyncio.run(_collect(collector))

    assert [observation.source_event_id for observation in observations] == ["2"]
    assert collector.stats["events_scanned"] == 2
    assert collector.stats["dropped_sampled_events"] == 1


def test_archive_observation_bounds_retained_code_and_serialized_size():
    item = event("1", "delegate task_id=alpha-9217")
    item["payload"]["issue"]["body"] = "```python\n" + ("x = 123456789\n" * 20_000) + "```"
    collector = collector_for([item], sample_rate=0.0)

    observation = asyncio.run(_collect(collector))[0]

    assert len(observation.text or "") <= collector.max_text_chars
    assert sum(len(block) for block in observation.code_blocks) <= 4 * 4_096
    assert len(observation.model_dump_json()) < 50_000


def test_compressed_download_limit_is_enforced():
    collector = collector_for([event("1", "task_id=alpha-9217")], max_download_bytes=1)
    with pytest.raises(RuntimeError, match="exceeded configured limit"):
        asyncio.run(_collect(collector))


def test_truncated_gzip_stream_is_not_checkpointable_as_complete():
    payload = gzip.compress(json.dumps(event("1", "ordinary issue")).encode() + b"\n")[:-8]
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=payload))
    collector = GHArchiveHourCollector(
        "2026-08-17-12", transport=transport, sample_rate=0.0
    )
    with pytest.raises(RuntimeError, match="checksum trailer"):
        asyncio.run(_collect(collector))


def test_ingestion_partition_checkpoint_round_trip(tmp_path):
    with SQLiteStore(tmp_path / "archive.db") as store:
        store.start_ingestion_partition("gharchive", "2026-08-17-12", "start")
        assert store.ingestion_partition("gharchive", "2026-08-17-12")["status"] == "running"
        store.finish_ingestion_partition(
            "gharchive",
            "2026-08-17-12",
            "complete",
            "finish",
            {"observations": 12},
        )
        result = store.ingestion_partition("gharchive", "2026-08-17-12")
    assert result["status"] == "complete"
    assert result["stats"] == {"observations": 12}


async def _collect(collector: GHArchiveHourCollector):
    return [observation async for observation in collector.collect()]
