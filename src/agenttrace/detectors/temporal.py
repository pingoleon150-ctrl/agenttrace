from __future__ import annotations

from statistics import median

from agenttrace.models import Observation, Signal


def detect_temporal_handoffs(observations: list[Observation]) -> list[Signal]:
    if len(observations) < 4 or len({o.actor for o in observations}) < 2:
        return []

    ordered = sorted(observations, key=lambda o: o.event_time)
    cross_actor_gaps: list[float] = []
    actor_changes = 0
    for left, right in zip(ordered, ordered[1:]):
        if left.actor != right.actor:
            actor_changes += 1
            cross_actor_gaps.append(max(0.0, (right.event_time - left.event_time).total_seconds()))

    if not cross_actor_gaps:
        return []

    med = median(cross_actor_gaps)
    density = actor_changes / max(1, len(ordered) - 1)
    latency_score = 1.0 if med <= 10 else 0.85 if med <= 60 else 0.60 if med <= 300 else 0.25
    score = min(1.0, 0.65 * latency_score + 0.35 * density)
    return [Signal(
        family="temporal",
        name="rapid_cross_actor_handoffs",
        score=score,
        observation_ids=[o.source_event_id for o in ordered],
        evidence=[f"median_cross_actor_gap_seconds={med:.2f}", f"actor_change_density={density:.2f}"],
    )]


def detect_periodicity(observations: list[Observation]) -> list[Signal]:
    if len(observations) < 6:
        return []
    ordered = sorted(observations, key=lambda o: o.event_time)
    gaps = [(b.event_time - a.event_time).total_seconds() for a, b in zip(ordered, ordered[1:])]
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
    return [Signal(
        family="temporal",
        name="periodic_activity",
        score=min(0.85, 0.35 + regular_fraction * 0.5),
        observation_ids=[o.source_event_id for o in ordered],
        evidence=[f"median_gap_seconds={med:.2f}", f"regular_fraction={regular_fraction:.2f}"],
    )]
