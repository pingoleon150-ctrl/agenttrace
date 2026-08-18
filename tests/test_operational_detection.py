from datetime import UTC, datetime, timedelta

from agenttrace.models import Observation, Provenance
from agenttrace.pipeline import analyze_cluster


def make(
    actor: str,
    event_id: str,
    text: str,
    seconds: int,
    *,
    actor_type: str | None = None,
    reply_to: str | None = None,
) -> Observation:
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
        reply_to=reply_to,
        metadata={"actor_type": actor_type},
        provenance=Provenance(url=f"https://github.com/example/repo/issues/7#{event_id}"),
    )


def test_direct_typed_exchange_reaches_operational_threshold():
    observations = [
        make("coordinator", "1", "Delegate task_id=alpha-9217 to worker", 0),
        make("worker", "2", "ACK task_id=alpha-9217", 5, reply_to="1"),
        make("worker", "3", "Task completed task_id=alpha-9217", 15, reply_to="1"),
    ]
    bundle = analyze_cluster("positive", observations, threshold=0.75)
    assert bundle.score.reviewable is True
    assert bundle.score.confidence == "high"
    assert {signal.family for signal in bundle.signals} >= {"artifact", "semantic"}


def test_reference_linked_exchange_in_one_thread_is_watchlist_only():
    observations = [
        make("coordinator", "1", "Delegate task_id=alpha-9217 to worker", 0),
        make("worker", "2", "ACK task_id=alpha-9217", 5),
        make("worker", "3", "Task completed task_id=alpha-9217", 15),
    ]
    bundle = analyze_cluster("positive-reference", observations, threshold=0.75)

    assert bundle.score.reviewable is False
    assert bundle.score.confidence == "medium"
    semantic = next(signal for signal in bundle.signals if signal.family == "semantic")
    assert semantic.depends_on == ["artifact"]


def test_reference_linked_cross_platform_exchange_uses_composite_high_route():
    observations = [
        make("coordinator", "1", "Delegate task_id=alpha-9217 to worker", 0),
        Observation(
            source="public-forum",
            source_event_id="2",
            observed_at=datetime.now(UTC),
            event_time=datetime.now(UTC) + timedelta(seconds=5),
            actor="worker",
            event_type="post",
            text="ACK task_id=alpha-9217",
            provenance=Provenance(url="https://forum.example/posts/2"),
        ),
        Observation(
            source="public-forum",
            source_event_id="3",
            observed_at=datetime.now(UTC),
            event_time=datetime.now(UTC) + timedelta(seconds=15),
            actor="worker",
            event_type="post",
            text="Task completed task_id=alpha-9217",
            provenance=Provenance(url="https://forum.example/posts/3"),
        ),
    ]
    bundle = analyze_cluster("positive-cross-platform", observations, threshold=0.75)

    assert bundle.score.reviewable is True
    assert "route=verified_relational_exchange" in bundle.score.reasons


def test_normal_review_bot_summary_stays_negative():
    commit = "4f3c2a19dd8f7e6a5b4c3d2e1f00112233445566"
    observations = [
        make("alice", "1", f"Please review commit {commit}; build and deploy later", 0),
        make("coderabbitai[bot]", "2", f"Automated review complete for {commit}", 20, actor_type="Bot"),
        make("mergify[bot]", "3", "All checks passed; automated merge ready", 39, actor_type="Bot"),
        make("alice", "4", "Context for reviewers: results from pytest are done", 55),
    ]
    bundle = analyze_cluster("negative", observations, threshold=0.75)
    assert bundle.score.reviewable is False
    assert bundle.score.confidence == "low"
    assert "artifact" not in bundle.score.families
    assert "graph" not in bundle.score.families


def test_copied_fingerprint_in_one_thread_is_not_an_identity_anchor():
    text = "task_id=deploy-9217 fingerprint: SHA256:abcdefghijklmnop"
    observations = [make("alice", "1", text, 0), make("bob", "2", text, 5)]
    bundle = analyze_cluster("copied-identity", observations, threshold=0.75)

    assert bundle.score.reviewable is False
    assert "identity" not in bundle.score.families
