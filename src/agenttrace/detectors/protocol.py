from __future__ import annotations

import re

from agenttrace.models import Observation, Signal

PATTERNS = {
    "task_identifier": re.compile(r"\b(?:task|job|work)[-_ ]?(?:id)?\s*[:=#]\s*[A-Za-z0-9._-]{4,}\b", re.I),
    "acknowledgement": re.compile(r"\b(?:ACK|NACK|acknowledged|received\s+task|task\s+accepted)\b", re.I),
    "heartbeat": re.compile(r"\b(?:heartbeat|healthcheck|lease\s+renewal|worker\s+alive)\b", re.I),
    "ttl_sequence": re.compile(r"\b(?:ttl|seq(?:uence)?|retry[_ -]?count|attempt)\s*[:=]\s*\d+\b", re.I),
    "coordination_queue": re.compile(r"\b(?:inbox|outbox|queue|worker|delegate|claim\s+task|coordinator)\b", re.I),
    "checkpoint": re.compile(r"\b(?:checkpoint|resume[_ -]?token|state[_ -]?id|continuation[_ -]?token)\b", re.I),
    "integrity": re.compile(r"\b(?:sha256|signature|public\s+key|fingerprint|nonce)\s*[:=]\s*[A-Za-z0-9+/=_:-]{8,}\b", re.I),
    "machine_envelope": re.compile(r"[\{,]\s*[\"']?(?:task_id|worker_id|status|result|nonce|sequence)[\"']?\s*:", re.I),
}


def detect_protocol(observation: Observation) -> list[Signal]:
    text = observation.text or ""
    hits = [name for name, pattern in PATTERNS.items() if pattern.search(text)]
    if not hits:
        return []
    score = min(1.0, 0.15 + 0.14 * len(hits))
    return [
        Signal(
            family="protocol",
            name="protocol_markers",
            score=score,
            observation_ids=[observation.source_event_id],
            evidence=hits,
        )
    ]
