from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from agenttrace.models import Observation


def cluster_observations(
    observations: list[Observation], window_minutes: int = 60
) -> dict[str, list[Observation]]:
    """Deterministic MVP clustering by repo/thread, then sliding time windows.

    Cross-platform/entity-aware clustering is intentionally a later phase. This function keeps
    the MVP auditable and easy to evaluate.
    """
    buckets: dict[str, list[Observation]] = defaultdict(list)
    for obs in observations:
        key = f"{obs.source}:{obs.repository or 'no-repo'}:{obs.thread_id or 'no-thread'}"
        buckets[key].append(obs)

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
