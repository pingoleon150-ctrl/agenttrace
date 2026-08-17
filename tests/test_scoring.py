from datetime import UTC, datetime

from agenttrace.models import Observation, Provenance, Signal
from agenttrace.scoring import score_cluster


def obs(actor: str, event_id: str) -> Observation:
    now = datetime.now(UTC)
    return Observation(
        source="t",
        source_event_id=event_id,
        observed_at=now,
        event_time=now,
        actor=actor,
        event_type="x",
        provenance=Provenance(url=f"https://example.com/{event_id}"),
    )


def test_requires_multiple_signal_families():
    result = score_cluster(
        [Signal(family="artifact", name="reuse", score=1.0)],
        [obs("a", "1"), obs("b", "2")],
        threshold=0.2,
    )
    assert result.reviewable is False


def test_reviewable_multi_signal_cluster():
    signals = [
        Signal(family="artifact", name="reuse", score=0.95),
        Signal(family="temporal", name="handoff", score=0.90),
        Signal(family="graph", name="motif", score=0.85),
        Signal(family="protocol", name="protocol", score=0.80),
    ]
    result = score_cluster(signals, [obs("a", "1"), obs("b", "2")], threshold=0.50)
    assert result.reviewable is True


def test_benign_penalty_can_suppress():
    signals = [
        Signal(family="artifact", name="reuse", score=1.0),
        Signal(family="temporal", name="handoff", score=1.0),
        Signal(family="graph", name="motif", score=1.0),
        Signal(family="protocol", name="protocol", score=1.0),
        Signal(family="semantic", name="sem", score=1.0),
        Signal(family="identity", name="id", score=1.0),
        Signal(family="benign", name="bot", score=1.0),
    ]
    result = score_cluster(
        signals, [obs("dependabot[bot]", "1"), obs("github-actions[bot]", "2")], threshold=0.6
    )
    assert result.reviewable is False
