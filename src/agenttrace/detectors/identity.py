from __future__ import annotations

import re
from collections import defaultdict

from agenttrace.models import Observation, Signal
from agenttrace.util import sha256_text

PUBKEY_RE = re.compile(r"\b(?:ssh-ed25519|ssh-rsa)\s+[A-Za-z0-9+/=]{20,}")
FINGERPRINT_RE = re.compile(
    r"\b(?:fingerprint|key_id)\s*[:=]\s*([A-Za-z0-9:_-]{8,})", re.IGNORECASE
)


def detect_shared_identity_markers(observations: list[Observation]) -> list[Signal]:
    markers: dict[str, set[str]] = defaultdict(set)
    ids: dict[str, list[str]] = defaultdict(list)
    contexts: dict[str, set[str]] = defaultdict(set)
    for obs in observations:
        text = "\n".join(
            line for line in (obs.text or "").splitlines() if not line.lstrip().startswith(">")
        )
        found = PUBKEY_RE.findall(text) + FINGERPRINT_RE.findall(text)
        for marker in found:
            markers[marker].add(
                obs.actor_key or f"{obs.platform}:actor:{obs.actor.lower()}"
            )
            ids[marker].append(obs.event_key or obs.source_event_id)
            contexts[marker].add(
                obs.conversation_key or obs.resource_key or obs.event_key or obs.source_event_id
            )

    shared = {
        marker: actors
        for marker, actors in markers.items()
        if len(actors) >= 2 and len(contexts[marker]) >= 2
    }
    if not shared:
        return []
    all_ids = sorted({oid for marker in shared for oid in ids[marker]})
    return [
        Signal(
            family="identity",
            name="shared_identity_marker",
            score=min(1.0, 0.65 + 0.08 * len(shared)),
            observation_ids=all_ids,
            evidence_groups=[f"identity:{sha256_text(marker)}" for marker in sorted(shared)],
            evidence=[
                f"marker_sha256={sha256_text(m)[:16]} actors={len(a)} "
                f"contexts={len(contexts[m])}"
                for m, a in list(shared.items())[:10]
            ],
        )
    ]
