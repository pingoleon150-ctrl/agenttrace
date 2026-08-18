from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from itertools import pairwise

from agenttrace.models import Observation, Signal

OPAQUE_RE = re.compile(r"(?<![A-Za-z0-9+/=])([A-Za-z0-9+/]{28,}={0,2})(?![A-Za-z0-9+/=])")
CREDENTIAL_RE = re.compile(
    r"\b(?:sk|token|relay|session|credential)[-_][A-Za-z0-9][A-Za-z0-9_-]{15,}\b",
    re.IGNORECASE,
)
WORD_RE = re.compile(r"[A-Za-z0-9]+")
MARKDOWN_STRUCTURE_RE = re.compile(r"(?m)^(?:#{1,4}\s|[-*+]\s|\d+[.)]\s|```|>\s)")


def detect_behavioral_signals(observations: list[Observation]) -> list[Signal]:
    """Detect longitudinal patterns that are stronger than isolated keywords."""
    signals: list[Signal] = []
    signals.extend(_detect_opaque_exchange(observations))
    signals.extend(_detect_shared_credential(observations))
    signals.extend(_detect_round_the_clock_persistence(observations))
    signals.extend(_detect_round_the_clock_pair(observations))
    signals.extend(_detect_cross_actor_style_reuse(observations))
    return signals


def _detect_opaque_exchange(observations: list[Observation]) -> list[Signal]:
    matches: list[tuple[Observation, str]] = []
    for observation in observations:
        for candidate in OPAQUE_RE.findall(observation.text or ""):
            if _opaque_quality(candidate) >= 0.72 and not _context_identifier(observation, candidate):
                matches.append((observation, candidate))
    actors = {item.actor_key for item, _value in matches}
    if len(matches) < 6 or len(actors) < 2:
        return []
    ordered = sorted(matches, key=lambda item: item[0].event_time)
    changes = sum(a.actor_key != b.actor_key for (a, _), (b, _) in pairwise(ordered))
    alternation = changes / max(1, len(ordered) - 1)
    gaps = [
        (right[0].event_time - left[0].event_time).total_seconds()
        for left, right in pairwise(ordered)
    ]
    fast_fraction = sum(gap <= 60 for gap in gaps) / max(1, len(gaps))
    if alternation < 0.60 or fast_fraction < 0.25:
        return []
    score = min(0.99, 0.68 + 0.20 * alternation + 0.12 * fast_fraction)
    return [
        Signal(
            family="artifact",
            name="opaque_cross_actor_exchange",
            score=score,
            observation_ids=[item.event_key or item.source_event_id for item, _ in ordered],
            evidence=[
                f"opaque_payload_count={len(matches)}",
                f"actor_count={len(actors)}",
                f"alternation={alternation:.2f}",
                f"fast_gap_fraction={fast_fraction:.2f}",
            ],
            evidence_groups=["behavior:opaque_exchange"],
            metadata={"exceptional_evidence": True},
        )
    ]


def _detect_shared_credential(observations: list[Observation]) -> list[Signal]:
    uses: dict[str, list[Observation]] = defaultdict(list)
    for observation in observations:
        for value in CREDENTIAL_RE.findall(observation.text or ""):
            if not _context_identifier(observation, value):
                uses[value.casefold()].append(observation)
    shared = {
        value: items
        for value, items in uses.items()
        if len({item.actor_key for item in items}) >= 2
        and len({item.resource_key for item in items}) >= 2
    }
    if not shared:
        return []
    items = [item for group in shared.values() for item in group]
    actor_count = len({item.actor_key for item in items})
    return [
        Signal(
            family="identity",
            name="shared_credential_across_identities",
            score=min(0.99, 0.88 + 0.02 * (actor_count - 2)),
            observation_ids=sorted({item.event_key or item.source_event_id for item in items}),
            evidence=[
                f"shared_credential_count={len(shared)}",
                f"actor_count={actor_count}",
                f"resource_count={len({item.resource_key for item in items})}",
            ],
            evidence_groups=["identity:shared_credential"],
            metadata={"exceptional_evidence": True},
        )
    ]


def _detect_round_the_clock_persistence(observations: list[Observation]) -> list[Signal]:
    signals: list[Signal] = []
    by_actor: dict[str, list[Observation]] = defaultdict(list)
    for observation in observations:
        by_actor[observation.actor_key or observation.actor.casefold()].append(observation)
    for actor, items in by_actor.items():
        if len(items) < 10:
            continue
        ordered = sorted(items, key=lambda item: item.event_time)
        span_hours = (ordered[-1].event_time - ordered[0].event_time).total_seconds() / 3600
        bins = {(item.event_time.hour // 4) for item in ordered}
        resources = {item.resource_key for item in items if item.resource_key}
        normalized = [_normalize_text(item.text or "") for item in items]
        dominant = Counter(value for value in normalized if value).most_common(1)
        repetition = dominant[0][1] / len(items) if dominant else 0.0
        if span_hours < 36 or len(bins) < 5 or (len(resources) < 2 and repetition < 0.45):
            continue
        score = min(
            0.96,
            0.48
            + 0.16 * min(1.0, span_hours / 72)
            + 0.16 * (len(bins) / 6)
            + 0.12 * min(1.0, len(resources) / 3)
            + 0.08 * repetition,
        )
        signals.append(
            Signal(
                family="behavior",
                name="round_the_clock_objective_persistence",
                score=score,
                observation_ids=[item.event_key or item.source_event_id for item in ordered],
                evidence=[
                    f"span_hours={span_hours:.1f}",
                    f"utc_four_hour_bins={len(bins)}",
                    f"resource_count={len(resources)}",
                    f"dominant_text_fraction={repetition:.2f}",
                ],
                evidence_groups=[f"behavior:activity:{actor}"],
                metadata={
                    "longitudinal": True,
                    "cross_resource": len(resources) >= 2,
                    "exceptional_evidence": len(resources) >= 3 and repetition >= 0.80,
                },
            )
        )
    return signals


def _detect_round_the_clock_pair(observations: list[Observation]) -> list[Signal]:
    by_actor: dict[str, list[Observation]] = defaultdict(list)
    for observation in observations:
        by_actor[observation.actor_key or observation.actor.casefold()].append(observation)
    qualifying: dict[str, list[Observation]] = {}
    for actor, items in by_actor.items():
        if len(items) < 8:
            continue
        ordered = sorted(items, key=lambda item: item.event_time)
        span = (ordered[-1].event_time - ordered[0].event_time).total_seconds() / 3600
        bins = {item.event_time.hour // 4 for item in items}
        if span >= 36 and len(bins) >= 4:
            qualifying[actor] = ordered
    if len(qualifying) < 2:
        return []
    items = [item for actor_items in qualifying.values() for item in actor_items]
    return [
        Signal(
            family="behavior",
            name="multi_actor_continuous_shift_coverage",
            score=min(0.98, 0.88 + 0.02 * len(qualifying)),
            observation_ids=[item.event_key or item.source_event_id for item in items],
            evidence=[
                f"qualifying_actor_count={len(qualifying)}",
                "minimum_span_hours=36",
                "minimum_utc_four_hour_bins_per_actor=4",
            ],
            evidence_groups=["behavior:continuous_shift_coverage"],
            metadata={
                "longitudinal": True,
                "cross_resource": len({item.resource_key for item in items}) >= 2,
                "exceptional_evidence": True,
            },
        )
    ]


def _detect_cross_actor_style_reuse(observations: list[Observation]) -> list[Signal]:
    by_template: dict[str, list[Observation]] = defaultdict(list)
    for observation in observations:
        if not MARKDOWN_STRUCTURE_RE.search(observation.text or ""):
            continue
        template = _normalize_text(observation.text or "")
        if len(template) >= 18:
            by_template[template].append(observation)
    reused = [
        items
        for items in by_template.values()
        if len(items) >= 4 and len({item.actor_key for item in items}) >= 2
    ]
    if not reused:
        return []
    items = [item for group in reused for item in group]
    return [
        Signal(
            family="semantic",
            name="cross_actor_structural_style_reuse",
            score=min(0.88, 0.62 + 0.03 * len(items)),
            observation_ids=sorted({item.event_key or item.source_event_id for item in items}),
            evidence=[
                f"reused_template_count={len(reused)}",
                f"matching_observation_count={len(items)}",
                f"actor_count={len({item.actor_key for item in items})}",
            ],
            evidence_groups=["semantic:style_reuse"],
        )
    ]


def _opaque_quality(value: str) -> float:
    alphabet = set(value.rstrip("="))
    if len(value) < 28 or len(alphabet) < 14:
        return 0.0
    counts = Counter(value.rstrip("="))
    length = sum(counts.values())
    entropy = -sum((count / length) * math.log2(count / length) for count in counts.values())
    return min(1.0, entropy / 5.2)


def _context_identifier(observation: Observation, value: str) -> bool:
    lowered = value.casefold()
    keys = {
        "sha",
        "commit_sha",
        "head_sha",
        "event_id",
        "node_id",
        "check_run_id",
        "workflow_run_id",
        "installation_id",
    }
    return any(str(observation.metadata.get(key, "")).casefold() == lowered for key in keys)


def _normalize_text(value: str) -> str:
    return " ".join(WORD_RE.findall(value.casefold()))
