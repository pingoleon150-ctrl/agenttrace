from __future__ import annotations

from collections import defaultdict

from agenttrace.models import ClusterScore, Observation, Signal

WEIGHTS = {
    "protocol": 0.15,
    "temporal": 0.20,
    "artifact": 0.25,
    "graph": 0.20,
    "semantic": 0.10,
    "identity": 0.10,
}
BENIGN_WEIGHT = 0.40
HIGH_VALUE = {"temporal", "artifact", "graph", "identity"}


def score_cluster(
    signals: list[Signal],
    observations: list[Observation],
    threshold: float = 0.60,
) -> ClusterScore:
    by_family: dict[str, float] = defaultdict(float)
    for signal in signals:
        by_family[signal.family] = max(by_family[signal.family], signal.score)

    positive = sum(WEIGHTS.get(family, 0.0) * value for family, value in by_family.items())
    benign = by_family.get("benign", 0.0)
    total = max(0.0, min(1.0, positive - BENIGN_WEIGHT * benign))

    fired = {family for family, value in by_family.items() if family != "benign" and value >= 0.40}
    actors = {o.actor for o in observations}
    provenance_complete = bool(observations) and all(o.provenance.url for o in observations)
    reviewable = (
        total >= threshold
        and len(fired) >= 3
        and bool(fired & HIGH_VALUE)
        and len(actors) >= 2
        and provenance_complete
        and benign < 0.75
    )

    reasons = [f"{family}={value:.2f}" for family, value in sorted(by_family.items()) if value >= 0.40]
    if benign:
        reasons.append(f"benign_penalty={BENIGN_WEIGHT * benign:.2f}")
    if not provenance_complete:
        reasons.append("provenance_incomplete")

    return ClusterScore(
        score=round(total, 4),
        families=dict(by_family),
        reviewable=reviewable,
        actor_count=len(actors),
        observation_count=len(observations),
        reasons=reasons,
    )
