from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from agenttrace.detectors.artifact_reuse import Artifact, extract_artifacts
from agenttrace.models import Observation
from agenttrace.util import sha256_text

MAX_LINKED_BUCKETS = 50


def cluster_observations(
    observations: list[Observation], window_minutes: int = 60
) -> dict[str, list[Observation]]:
    """Cluster by namespaced resource/conversation, then deterministic time windows."""
    buckets: dict[str, list[Observation]] = defaultdict(list)
    bucket_by_event: dict[str, str] = {}
    for obs in observations:
        key = (
            obs.conversation_key
            or obs.resource_key
            or obs.event_key
            or f"{obs.platform}:event:{obs.source}:{obs.source_event_id}"
        )
        buckets[key].append(obs)
        bucket_by_event[obs.event_key or obs.source_event_id] = key

    buckets = _link_typed_artifact_buckets(buckets, bucket_by_event)

    result: dict[str, list[Observation]] = {}
    window = timedelta(minutes=window_minutes)
    for key, items in buckets.items():
        items.sort(key=lambda o: o.event_time)
        group: list[Observation] = []
        start = None
        index = 0
        for obs in items:
            if start is None or obs.event_time - start <= window:
                if start is None:
                    start = obs.event_time
                group.append(obs)
            else:
                result[f"{key}:{index}"] = group
                index += 1
                group = [obs]
                start = obs.event_time
        if group:
            result[f"{key}:{index}"] = group
    return result


def _link_typed_artifact_buckets(
    buckets: dict[str, list[Observation]], bucket_by_event: dict[str, str]
) -> dict[str, list[Observation]]:
    """Link bounded cross-resource candidates through auditable typed artifacts only."""
    parent = {key: key for key in buckets}
    component_size = {key: 1 for key in buckets}

    def find(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            if component_size[left_root] + component_size[right_root] > MAX_LINKED_BUCKETS:
                return
            parent[right_root] = left_root
            component_size[left_root] += component_size[right_root]

    occurrences: dict[Artifact, list[tuple[Observation, str]]] = defaultdict(list)
    for items in buckets.values():
        for obs in items:
            bucket_key = bucket_by_event[obs.event_key or obs.source_event_id]
            for artifact in extract_artifacts(obs):
                if artifact.kind.startswith("marker:") or artifact.kind == "code":
                    occurrences[artifact].append((obs, bucket_key))

    for matches in occurrences.values():
        keys = sorted({key for _obs, key in matches})
        actors = {obs.actor_key for obs, _key in matches}
        platforms = {obs.platform for obs, _key in matches}
        resources = {obs.resource_key for obs, _key in matches if obs.resource_key}
        independent_scope = len(platforms) >= 2 or len(resources) >= 2
        if not (2 <= len(keys) <= 10 and len(actors) >= 2 and independent_scope):
            continue
        for key in keys[1:]:
            union(keys[0], key)

    members: dict[str, list[str]] = defaultdict(list)
    for key in buckets:
        members[find(key)].append(key)

    merged: dict[str, list[Observation]] = {}
    for keys in members.values():
        stable_keys = sorted(keys)
        merged_key = (
            stable_keys[0]
            if len(stable_keys) == 1
            else f"linked:{sha256_text(chr(10).join(stable_keys))[:20]}"
        )
        merged[merged_key] = [obs for key in stable_keys for obs in buckets[key]]
    return merged
