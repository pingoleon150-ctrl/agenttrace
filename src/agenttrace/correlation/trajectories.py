from __future__ import annotations

import re
from collections import defaultdict
from datetime import timedelta

from agenttrace.detectors.behavior import CREDENTIAL_RE, OPAQUE_RE, _opaque_quality
from agenttrace.models import Observation
from agenttrace.util import sha256_text


def longitudinal_candidates(observations: list[Observation]) -> dict[str, list[Observation]]:
    """Build bounded high-specificity candidates that repository buckets cannot express."""
    candidates: dict[str, list[Observation]] = {}
    by_actor: dict[str, list[Observation]] = defaultdict(list)
    by_resource: dict[str, list[Observation]] = defaultdict(list)
    by_credential: dict[str, list[Observation]] = defaultdict(list)
    opaque_by_scaffold: dict[str, list[Observation]] = defaultdict(list)
    for item in observations:
        by_actor[item.actor_key or item.actor.casefold()].append(item)
        if item.resource_key:
            by_resource[item.resource_key].append(item)
        text = item.text or ""
        opaque_values = [value for value in OPAQUE_RE.findall(text) if _opaque_quality(value) >= 0.72]
        if opaque_values:
            scaffold = _opaque_scaffold(text)
            if len(scaffold) >= 8:
                opaque_by_scaffold[scaffold].append(item)
        for value in CREDENTIAL_RE.findall(text):
            by_credential[value.casefold()].append(item)

    for actor, items in by_actor.items():
        if _spans(items, 36) and len(items) >= 10 and len({item.resource_key for item in items}) >= 2:
            candidates[f"trajectory:actor:{sha256_text(actor)[:16]}"] = items
    for resource, items in by_resource.items():
        if _spans(items, 36) and len(items) >= 16 and len({item.actor_key for item in items}) >= 2:
            candidates[f"trajectory:resource:{sha256_text(resource)[:16]}"] = items
    for value, items in by_credential.items():
        if (
            len(items) >= 4
            and len({item.actor_key for item in items}) >= 2
            and len({item.resource_key for item in items}) >= 2
        ):
            candidates[f"trajectory:credential:{sha256_text(value)[:16]}"] = items
    for scaffold, scaffold_items in opaque_by_scaffold.items():
        for index, items in enumerate(_sessionize(scaffold_items, timedelta(hours=2))):
            if len(items) >= 6 and len({item.actor_key for item in items}) >= 2:
                digest = sha256_text(scaffold)[:10]
                candidates[f"trajectory:opaque:{digest}:{index}:{_event_digest(items)}"] = items
    return candidates


def _spans(items: list[Observation], hours: float) -> bool:
    if len(items) < 2:
        return False
    times = [item.event_time for item in items]
    return (max(times) - min(times)).total_seconds() >= hours * 3600


def _sessionize(items: list[Observation], maximum_gap: timedelta) -> list[list[Observation]]:
    ordered = sorted(items, key=lambda item: item.event_time)
    groups: list[list[Observation]] = []
    for item in ordered:
        if not groups or item.event_time - groups[-1][-1].event_time > maximum_gap:
            groups.append([item])
        else:
            groups[-1].append(item)
    return groups


def _event_digest(items: list[Observation]) -> str:
    keys = sorted(item.event_key or item.source_event_id for item in items)
    return sha256_text("\n".join(keys))[:12]


def _opaque_scaffold(text: str) -> str:
    without_payloads = OPAQUE_RE.sub("<opaque>", text.casefold())
    without_numbers = re.sub(r"\d+", "<number>", without_payloads)
    return " ".join(without_numbers.split())
