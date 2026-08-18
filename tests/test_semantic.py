from datetime import UTC, datetime, timedelta

from agenttrace.detectors.semantic import detect_coordination_exchange
from agenttrace.models import Observation, Provenance


def make(actor: str, event_id: str, text: str, seconds: int = 0) -> Observation:
    now = datetime.now(UTC)
    return Observation(
        source="test",
        source_event_id=event_id,
        observed_at=now,
        event_time=now + timedelta(seconds=seconds),
        actor=actor,
        event_type="comment",
        text=text,
        repository="example/repo",
        thread_id="1",
        provenance=Provenance(url=f"https://example.test/{event_id}"),
    )


def test_linked_delegate_ack_result_is_strong():
    observations = [
        make("coordinator", "1", "Delegate task_id=alpha-9217 to worker", 0),
        make("worker", "2", "ACK task_id=alpha-9217", 5),
        make("worker", "3", "Task completed task_id=alpha-9217", 15),
    ]
    signals = detect_coordination_exchange(observations)
    assert signals
    assert signals[0].score >= 0.90
    assert "distinct_acknowledgements=1" in signals[0].evidence
    assert signals[0].depends_on == ["artifact"]


def test_native_reply_exchange_is_independent_of_artifact_family():
    delegation = make("coordinator", "1", "Delegate this task to worker", 0)
    result = make("worker", "2", "Task completed", 5)
    result.reply_to = "1"
    result.parent_key = delegation.event_key

    signals = detect_coordination_exchange([delegation, result])

    assert signals
    assert signals[0].depends_on == []
    assert "link_types=native_reply" in signals[0].evidence


def test_distinct_native_ack_reply_chain_is_verified():
    delegation = make("coordinator", "1", "Please run this check", 0)
    acknowledgement = make("worker", "2", "ACK", 5)
    acknowledgement.parent_key = delegation.event_key
    result = make("worker", "3", "Task completed; reporting back", 10)
    result.parent_key = acknowledgement.event_key

    signals = detect_coordination_exchange([delegation, acknowledgement, result])

    assert signals
    assert signals[0].score >= 0.90
    assert signals[0].metadata["verified_native_trajectories"] == 1


def test_result_event_cannot_count_as_its_own_acknowledgement():
    observations = [
        make("coordinator", "1", "Assign task_id=alpha-9217", 0),
        make("worker", "2", "ACK; task completed task_id=alpha-9217", 5),
    ]
    signals = detect_coordination_exchange(observations)

    assert signals
    assert signals[0].score < 0.90
    assert signals[0].metadata["distinct_acknowledgements"] == 0


def test_quoted_or_collapsed_summary_does_not_form_exchange():
    observations = [
        make("coordinator", "1", "Delegate task_id=alpha-9217", 0),
        make(
            "review-bot[bot]",
            "2",
            "> ACK task_id=alpha-9217\n<details>Task completed task_id=alpha-9217</details>",
            5,
        ),
    ]
    assert detect_coordination_exchange(observations) == []


def test_same_raw_handle_across_platforms_is_not_a_cross_actor_exchange():
    delegation = make("alice", "1", "Delegate task_id=alpha-9217", 0)
    result = Observation(
        source="public-forum",
        source_event_id="2",
        observed_at=datetime.now(UTC),
        event_time=datetime.now(UTC) + timedelta(seconds=5),
        actor="alice",
        event_type="post",
        text="Task completed task_id=alpha-9217",
        provenance=Provenance(url="https://forum.example/posts/2"),
    )
    assert detect_coordination_exchange([delegation, result]) == []


def test_isolated_generic_words_are_not_semantic_exchange():
    observations = [
        make("a", "1", "Context for reviewers: results from pytest are done."),
        make("b", "2", "Build and deploy documentation."),
    ]
    assert detect_coordination_exchange(observations) == []


def test_negated_delegation_is_not_exchange():
    observations = [
        make("a", "1", "Do not assign task_id=alpha-9217 to this worker."),
        make("b", "2", "Task completed task_id=alpha-9217"),
    ]
    assert detect_coordination_exchange(observations) == []
