import asyncio
from datetime import UTC, datetime, timedelta

from agenttrace.campaign import CampaignResult
from agenttrace.models import Observation, Provenance
from agenttrace.monitor import take_watch_query_batch, watch_cycle
from agenttrace.pipeline import analyze_cluster
from agenttrace.storage.sqlite import SQLiteStore


def observation(actor: str, event_id: str, text: str, seconds: int = 0) -> Observation:
    now = datetime.now(UTC)
    return Observation(
        source="github-thread-search",
        source_event_id=event_id,
        observed_at=now,
        event_time=now + timedelta(seconds=seconds),
        actor=actor,
        event_type="issue_comment",
        text=text,
        repository="example/repo",
        thread_id="7",
        provenance=Provenance(url=f"https://github.com/example/repo/issues/7#{event_id}"),
    )


def test_watchlist_keeps_ranked_low_candidates_when_no_medium_exists(tmp_path, monkeypatch):
    async def empty_campaign(*_args, **_kwargs):
        return CampaignResult(queries=["q"], sources=[])

    monkeypatch.setattr("agenttrace.monitor.run_campaign", empty_campaign)
    with SQLiteStore(tmp_path / "monitor.db") as store:
        store.upsert_observation(
            observation("alice", "1", "task_id=alpha-9217 heartbeat coordinator")
        )
        result = asyncio.run(watch_cycle(["q"], {}, store, threshold=0.75))

    assert result.state == "watching"
    assert result.watchlist
    assert result.watchlist[0]["confidence"] == "low"
    assert result.watchlist[0]["priority_score"] > 0


def test_historical_high_bundle_without_new_evidence_does_not_repause(tmp_path, monkeypatch):
    async def empty_campaign(*_args, **_kwargs):
        return CampaignResult(queries=["q"], sources=[])

    monkeypatch.setattr("agenttrace.monitor.run_campaign", empty_campaign)
    observations = [
        observation("coordinator", "1", "Delegate task_id=alpha-9217 to worker", 0),
        observation("worker", "2", "ACK task_id=alpha-9217", 5),
        observation("worker", "3", "Task completed task_id=alpha-9217", 10),
    ]
    with SQLiteStore(tmp_path / "monitor.db") as store:
        store.upsert_observations_batch(observations)
        result = asyncio.run(watch_cycle(["q"], {}, store, threshold=0.75))
        assert store.pending_alert() is None

    assert result.state == "watching"
    assert result.alert is None


def test_pending_alert_does_not_advance_query_cursor(tmp_path):
    with SQLiteStore(tmp_path / "monitor.db") as store:
        bundle = analyze_cluster(
            "candidate",
            [observation("alice", "1", "task_id=alpha-9217")],
            threshold=0.75,
        )
        store.create_alert("candidate", "summary", bundle)

        assert take_watch_query_batch(store, ["one", "two"], 1) == []

        store.resolve_alert(1, "reviewed", datetime.now(UTC).isoformat())
        assert take_watch_query_batch(store, ["one", "two"], 1) == ["one"]
