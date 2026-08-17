from datetime import UTC, datetime

from agenttrace.detectors.protocol import detect_protocol
from agenttrace.models import Observation, Provenance


def test_protocol_markers():
    now = datetime.now(UTC)
    observation = Observation(
        source="t",
        source_event_id="1",
        observed_at=now,
        event_time=now,
        actor="a",
        event_type="post",
        text="TASK-ID: job-1234 ACK retry_count=2 heartbeat",
        provenance=Provenance(url="https://example.com/1"),
    )
    signals = detect_protocol(observation)
    assert signals
    assert signals[0].score > 0.5
