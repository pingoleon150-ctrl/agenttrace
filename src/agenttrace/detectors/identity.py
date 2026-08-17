from __future__ import annotations

import re
from collections import defaultdict

from agenttrace.models import Observation, Signal

PUBKEY_RE = re.compile(r"\b(?:ssh-ed25519|ssh-rsa)\s+[A-Za-z0-9+/=]{20,}")
FINGERPRINT_RE = re.compile(r"\b(?:fingerprint|key_id|worker_id)\s*[:=]\s*([A-Za-z0-9:_-]{8,})", re.I)


def detect_shared_identity_markers(observations: list[Observation]) -> list[Signal]:
    markers: dict[str, set[str]] = defaultdict(set)
    ids: dict[str, list[str]] = defaultdict(list)
    for obs in observations:
        text = obs.text or ""
        found = PUBKEY_RE.findall(text) + FINGERPRINT_RE.findall(text)
        for marker in found:
            markers[marker].add(obs.actor)
            ids[marker].append(obs.source_event_id)

    shared = {m: actors for m, actors in markers.items() if len(actors) >= 2}
    if not shared:
        return []
    all_ids = sorted({oid for marker in shared for oid in ids[marker]})
    return [Signal(
        family="identity",
        name="shared_identity_marker",
        score=min(1.0, 0.65 + 0.08 * len(shared)),
        observation_ids=all_ids,
        evidence=[f"marker={m[:48]} actors={','.join(sorted(a))}" for m, a in list(shared.items())[:10]],
    )]
