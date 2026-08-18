from __future__ import annotations

from itertools import pairwise
from statistics import median

from agenttrace.detectors.artifact_reuse import extract_artifacts
from agenttrace.models import Observation, Signal


def detect_temporal_handoffs(observations: list[Observation]) -> list[Signal]:
    if len(observations) < 4 or len({_actor_identity(o) for o in observations}) < 2:
        return []

    ordered = sorted(observations, key=lambda o: o.event_time)
    cross_actor_gaps: list[float] = []
    actor_changes = 0
    causes: set[str] = set()
    for left, right in pairwise(ordered):
        cause = _causal_link(left, right)
        if _actor_identity(left) != _actor_identity(right) and cause:
            actor_changes += 1
            causes.add(cause)
            cross_actor_gaps.append(max(0.0, (right.event_time - left.event_time).total_seconds()))

    if not cross_actor_gaps:
        return []

    med = median(cross_actor_gaps)
    density = actor_changes / max(1, len(ordered) - 1)
    latency_score = 1.0 if med <= 10 else 0.85 if med <= 60 else 0.60 if med <= 300 else 0.25
    score = min(1.0, 0.65 * latency_score + 0.35 * density)
    return [
        Signal(
            family="temporal",
            name="rapid_cross_actor_handoffs",
            score=score,
            observation_ids=[o.event_key or o.source_event_id for o in ordered],
            depends_on=["artifact"] if "shared_artifact" in causes else [],
            evidence=[
                f"median_cross_actor_gap_seconds={med:.2f}",
                f"actor_change_density={density:.2f}",
            ],
        )
    ]


def _causal_link(left: Observation, right: Observation) -> str | None:
    if right.parent_key == left.event_key:
        return "native_reply"
    if extract_artifacts(left) & extract_artifacts(right):
        return "shared_artifact"
    return None


def _actor_identity(observation: Observation) -> str:
    return observation.actor.strip().casefold()


def detect_periodicity(observations: list[Observation]) -> list[Signal]:
    if len(observations) < 6:
        return []
    ordered = sorted(observations, key=lambda o: o.event_time)
    gaps = [(b.event_time - a.event_time).total_seconds() for a, b in pairwise(ordered)]
    gaps = [g for g in gaps if g > 0]
    if len(gaps) < 5:
        return []
    med = median(gaps)
    if med <= 0:
        return []
    deviations = [abs(g - med) / med for g in gaps]
    regular_fraction = sum(1 for d in deviations if d <= 0.10) / len(deviations)
    if regular_fraction < 0.60:
        return []
    return [
        Signal(
            family="temporal",
            name="periodic_activity",
            score=min(0.85, 0.35 + regular_fraction * 0.5),
            observation_ids=[o.event_key or o.source_event_id for o in ordered],
            evidence=[f"median_gap_seconds={med:.2f}", f"regular_fraction={regular_fraction:.2f}"],
        )
    ]
