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


class FakeReviewer:
    reviewer_name = "test-reviewer"
    model_name = "test-model"

    async def classify(self, _bundle):
        return {
            "classification": "ai_assisted_collaboration",
            "autonomy_level": "human_supervised",
            "confidence": "high",
            "summary": "Public coordination with explicit agent assistance.",
            "intent": "Software maintenance.",
            "human_risk": "Low.",
            "company_affiliation": "Not established.",
            "agents_identified": ["coding agent"],
            "models_identified": [],
            "evidence_for": ["delegate-result exchange"],
            "evidence_against": ["human approval remains visible"],
            "recommended_disposition": "reviewed",
        }


def test_auto_review_classifies_reports_and_continues(tmp_path, monkeypatch):
    observations = [
        observation("coordinator", "1", "Delegate task_id=alpha-9217 to worker", 0),
        observation("worker", "2", "ACK task_id=alpha-9217", 5),
        observation("worker", "3", "Task completed task_id=alpha-9217", 10),
    ]
    bundle = analyze_cluster("candidate", observations, threshold=0.75)
    bundle.score.reviewable = True

    async def campaign(*_args, **_kwargs):
        result = CampaignResult(queries=["q"], sources=[])
        result.observations = observations
        return result

    monkeypatch.setattr("agenttrace.monitor.run_campaign", campaign)
    monkeypatch.setattr("agenttrace.monitor.analyze_observations", lambda *_a, **_k: [bundle])
    report = tmp_path / "findings.md"
    with SQLiteStore(tmp_path / "monitor.db") as store:
        result = asyncio.run(
            watch_cycle(
                ["q"], {}, store, threshold=0.75, reviewer=FakeReviewer(), report_path=report
            )
        )
        findings = store.monitor_findings()

    assert result.state == "watching"
    assert result.classified_alerts[0]["classification"]["autonomy_level"] == "human_supervised"
    assert findings[0]["status"] == "reviewed"
    assert findings[0]["model"] == "test-model"
    assert "AI-assisted" not in report.read_text()  # Content comes from the structured result.
    assert "ai_assisted_collaboration" in report.read_text()
