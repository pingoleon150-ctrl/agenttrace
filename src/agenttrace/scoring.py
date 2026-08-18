from __future__ import annotations

from agenttrace.models import ClusterScore, Observation, Signal

RELIABILITY = {
    "protocol": 0.90,
    "temporal": 0.65,
    "artifact": 0.95,
    "graph": 0.70,
    "semantic": 1.00,
    "identity": 1.00,
}
ANCHOR_FAMILIES = {"artifact", "semantic", "identity"}
FAMILY_FLOOR = 0.35
STRONG_FAMILY = 0.68


def score_cluster(
    signals: list[Signal],
    observations: list[Observation],
    threshold: float = 0.60,
) -> ClusterScore:
    selected: dict[str, Signal] = {}
    for signal in signals:
        if signal.family not in selected or signal.score > selected[signal.family].score:
            selected[signal.family] = signal
    by_family = {family: signal.score for family, signal in selected.items()}

    effective = {
        family: RELIABILITY[family] * value
        for family, value in by_family.items()
        if family in RELIABILITY and value >= FAMILY_FLOOR
    }
    fired = set(effective)
    components = _dependency_components(fired, selected)
    component_strengths = [max(effective[family] for family in component) for component in components]
    strengths = sorted(component_strengths, reverse=True)
    positive = sum(
        coefficient * value
        for coefficient, value in zip((0.52, 0.31, 0.17), strengths, strict=False)
    )
    if len(strengths) >= 2:
        positive += 0.03
    if len(strengths) >= 3:
        positive += 0.03
    collapsed_count = len(fired) - len(components)
    positive += min(0.06, 0.03 * collapsed_count)
    verified_exchange = _has_verified_exchange(selected, fired)
    if verified_exchange:
        positive = max(positive, 0.80)
    benign = by_family.get("benign", 0.0)
    total = max(0.0, min(1.0, positive * (1.0 - 0.65 * benign)))

    anchor_components = [
        component
        for component in components
        if any(family in ANCHOR_FAMILIES for family in component)
    ]
    strong_anchor_components = [
        component
        for component in anchor_components
        if any(
            family in ANCHOR_FAMILIES and effective[family] >= STRONG_FAMILY
            for family in component
        )
    ]
    actors = {o.actor.strip().casefold() for o in observations}
    provenance_complete = bool(observations) and all(o.provenance.url for o in observations)
    eligible = len(actors) >= 2 and provenance_complete and benign < 0.80
    reviewable = (
        total >= threshold
        and (len(strong_anchor_components) >= 2 or verified_exchange)
        and eligible
    )
    medium = (
        not reviewable
        and eligible
        and total >= max(0.45, threshold - 0.25)
        and (
            (bool(strong_anchor_components) and (len(components) >= 2 or collapsed_count > 0))
            or len(anchor_components) >= 2
        )
    )
    confidence = "high" if reviewable else "medium" if medium else "low"

    reasons = [
        f"{family}={value:.2f}" for family, value in sorted(by_family.items()) if value >= FAMILY_FLOOR
    ]
    if benign:
        reasons.append(f"benign_multiplier={1.0 - 0.65 * benign:.2f}")
    reasons.append(f"confidence={confidence}")
    if collapsed_count:
        reasons.append(f"correlated_families_collapsed={collapsed_count}")
    if verified_exchange:
        reasons.append("route=verified_relational_exchange")
    elif len(strong_anchor_components) >= 2:
        reasons.append("route=two_independent_strong_anchors")
    elif medium:
        reasons.append("route=analyst_watchlist")
    if not provenance_complete:
        reasons.append("provenance_incomplete")

    return ClusterScore(
        score=round(total, 4),
        families=dict(by_family),
        confidence=confidence,
        reviewable=reviewable,
        actor_count=len(actors),
        observation_count=len(observations),
        reasons=reasons,
    )


def _dependency_components(fired: set[str], selected: dict[str, Signal]) -> list[set[str]]:
    """Collapse families that explicitly reuse the same underlying evidence."""
    parent = {family: family for family in fired}

    def find(family: str) -> str:
        while parent[family] != family:
            parent[family] = parent[parent[family]]
            family = parent[family]
        return family

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for family in fired:
        for dependency in selected[family].depends_on:
            if dependency in fired:
                union(family, dependency)

    grouped: dict[str, set[str]] = {}
    for family in fired:
        grouped.setdefault(find(family), set()).add(family)
    return list(grouped.values())


def _has_verified_exchange(selected: dict[str, Signal], fired: set[str]) -> bool:
    """Recognize a complete native or cross-context relational trajectory."""
    semantic = selected.get("semantic")
    if not semantic or semantic.name != "linked_coordination_exchange" or semantic.score < 0.90:
        return False
    native = int(semantic.metadata.get("verified_native_trajectories") or 0)
    cross_context = int(semantic.metadata.get("verified_cross_context_trajectories") or 0)
    return native > 0 or (cross_context > 0 and "artifact" in fired)
