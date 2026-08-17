from datetime import UTC, datetime

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
    signals = detect_cross_actor_reuse([make("a", "1", token), make("b", "2", token)])
    assert signals
    assert signals[0].family == "artifact"
