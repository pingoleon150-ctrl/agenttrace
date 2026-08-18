from __future__ import annotations

from agenttrace.collectors.base import Collector
from agenttrace.correlation.cluster import cluster_observations
from agenttrace.correlation.graph import build_coordination_graph, detect_graph_motifs
from agenttrace.detectors.artifact_reuse import detect_cross_actor_reuse
from agenttrace.detectors.benign import detect_benign_automation
from agenttrace.detectors.identity import detect_shared_identity_markers
from agenttrace.detectors.protocol import detect_protocol
from agenttrace.detectors.semantic import detect_coordination_exchange
from agenttrace.detectors.temporal import detect_periodicity, detect_temporal_handoffs
from agenttrace.models import EvidenceBundle, Observation, Signal
from agenttrace.scoring import score_cluster
from agenttrace.storage.sqlite import SQLiteStore
from agenttrace.util import utcnow


async def collect_to_store(
    collector: Collector, store: SQLiteStore, batch_size: int = 500
) -> list[Observation]:
    observations: list[Observation] = []
    pending: list[Observation] = []
    async for observation in collector.collect():
        observations.append(observation)
        pending.append(observation)
        if len(pending) >= max(1, batch_size):
            store.upsert_observations_batch(pending)
            pending.clear()
    store.upsert_observations_batch(pending)
    return observations


def analyze_cluster(
    cluster_id: str, observations: list[Observation], threshold: float = 0.60
) -> EvidenceBundle:
    signals: list[Signal] = []
    for observation in observations:
        signals.extend(detect_protocol(observation))

    signals.extend(detect_coordination_exchange(observations))
    signals.extend(detect_cross_actor_reuse(observations))
    signals.extend(detect_shared_identity_markers(observations))
    signals.extend(detect_temporal_handoffs(observations))
    signals.extend(detect_periodicity(observations))
    signals.extend(detect_benign_automation(observations))
    signals.extend(detect_graph_motifs(build_coordination_graph(observations)))

    score = score_cluster(signals, observations, threshold=threshold)
    return EvidenceBundle(
        cluster_id=cluster_id,
        created_at=utcnow(),
        actors=sorted({o.actor for o in observations}),
        observations=sorted(observations, key=lambda o: o.event_time),
        signals=signals,
        score=score,
        uncertainty=(
            "This cluster exhibits multiple public coordination signals and requires analyst review. "
            "The score does not establish that any actor is an AI agent."
            if score.reviewable
            else "Insufficient independent evidence for an agentic-coordination hypothesis."
        ),
    )


def analyze_observations(
    observations: list[Observation], threshold: float = 0.60, window_minutes: int = 60
) -> list[EvidenceBundle]:
    clusters = cluster_observations(observations, window_minutes=window_minutes)
    return [
        analyze_cluster(cluster_id, items, threshold=threshold)
        for cluster_id, items in clusters.items()
    ]
