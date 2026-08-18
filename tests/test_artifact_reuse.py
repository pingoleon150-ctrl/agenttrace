from datetime import UTC, datetime

from agenttrace.correlation.graph import build_coordination_graph, detect_graph_motifs
from agenttrace.detectors.artifact_reuse import detect_cross_actor_reuse
from agenttrace.models import Observation, Provenance


def make(actor, event_id, text):
    now = datetime.now(UTC)
    return Observation(
        source="t",
        source_event_id=event_id,
        observed_at=now,
        event_time=now,
        actor=actor,
        event_type="post",
        text=text,
        repository="r/x",
        thread_id="1",
        provenance=Provenance(url=f"https://example.com/{event_id}"),
    )


def test_cross_actor_token_reuse():
    token = "artifact-7f9c2a11-checkpoint-8891"
    signals = detect_cross_actor_reuse(
        [make("a", "1", f"nonce={token}"), make("b", "2", f"nonce={token}")]
    )
    assert signals
    assert signals[0].family == "artifact"


def test_common_github_identifiers_are_not_artifacts():
    noise = (
        "commit 4f3c2a19dd8f7e6a5b4c3d2e1f00112233445566 "
        "run 550e8400-e29b-41d4-a716-446655440000 "
        "utm_campaign=release-2026 sequence-range"
    )
    assert detect_cross_actor_reuse([make("a", "1", noise), make("b", "2", noise)]) == []


def test_quoted_marker_does_not_count_as_propagation():
    token = "coordination-7f9c2a11"
    observations = [
        make("a", "1", f"task_id={token}"),
        make("review-bot[bot]", "2", f"> task_id={token}\nAutomated review complete"),
    ]
    assert detect_cross_actor_reuse(observations) == []


def test_artifact_reuse_does_not_create_graph_family():
    token = "coordination-7f9c2a11"
    observations = [
        make("a", "1", f"nonce={token}"),
        make("b", "2", f"nonce={token}"),
    ]
    assert detect_cross_actor_reuse(observations)
    assert detect_graph_motifs(build_coordination_graph(observations)) == []
