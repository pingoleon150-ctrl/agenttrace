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
    assert result.confidence == "low"


def test_two_strong_independent_families_can_be_reviewable():
    signals = [
        Signal(family="artifact", name="reuse", score=0.98),
        Signal(family="semantic", name="exchange", score=0.95),
    ]
    result = score_cluster(signals, [obs("a", "1"), obs("b", "2")], threshold=0.75)
    assert result.reviewable is True
    assert result.confidence == "high"


def test_exceptional_score_preserves_effective_signal_strength():
    result = score_cluster(
        [
            Signal(
                family="artifact",
                name="opaque_exchange",
                score=0.92,
                metadata={"exceptional_evidence": True},
            )
        ],
        [obs("a", "1"), obs("b", "2")],
        threshold=0.75,
    )
    assert result.score == 0.874
    assert result.score != 0.85
    assert "exceptional_strength=0.87" in result.reasons


def test_correlated_families_do_not_count_as_two_anchors():
    signals = [
        Signal(family="artifact", name="reuse", score=0.98),
        Signal(
            family="semantic",
            name="exchange",
            score=0.95,
            depends_on=["artifact"],
        ),
    ]
    result = score_cluster(signals, [obs("a", "1"), obs("b", "2")], threshold=0.75)
    assert result.reviewable is False
    assert result.confidence == "medium"
    assert "correlated_families_collapsed=1" in result.reasons


def test_one_anchor_with_multiple_corroborators_is_watchlist_only():
    signals = [
        Signal(family="artifact", name="reuse", score=0.95),
        Signal(family="temporal", name="handoff", score=0.90),
        Signal(family="graph", name="motif", score=0.85),
        Signal(family="protocol", name="protocol", score=0.80),
    ]
    result = score_cluster(signals, [obs("a", "1"), obs("b", "2")], threshold=0.50)
    assert result.reviewable is False
    assert result.confidence == "medium"


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


def test_same_raw_handle_on_two_platforms_does_not_satisfy_actor_gate():
    github = obs("alice", "1")
    forum = Observation(
        source="public-forum",
        source_event_id="2",
        observed_at=github.observed_at,
        event_time=github.event_time,
        actor="alice",
        event_type="post",
        provenance=Provenance(url="https://forum.example/posts/2"),
    )
    result = score_cluster(
        [
            Signal(family="artifact", name="reuse", score=0.98),
            Signal(family="semantic", name="exchange", score=0.95),
        ],
        [github, forum],
        threshold=0.75,
    )
    assert result.reviewable is False
    assert result.actor_count == 1
