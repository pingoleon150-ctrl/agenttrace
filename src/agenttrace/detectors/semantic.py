from __future__ import annotations

import re

from agenttrace.models import Observation, Signal

SEMANTIC_PATTERNS = {
    "delegation": re.compile(r"\b(?:delegate|assign|take this task|you handle|worker\s+\w+.*(?:do|run|check))\b", re.I),
    "result_return": re.compile(r"\b(?:result(?:s)?|completed|done|returning|report back|findings)\b", re.I),
    "state_transfer": re.compile(r"\b(?:resume from|continue from|previous state|context|checkpoint|state transfer)\b", re.I),
    "tooling": re.compile(r"\b(?:tool call|sandbox|browser tool|terminal|execution environment|token budget)\b", re.I),
}


def detect_coordination_semantics(observation: Observation) -> list[Signal]:
    text = observation.text or ""
    hits = [name for name, pattern in SEMANTIC_PATTERNS.items() if pattern.search(text)]
    if not hits:
        return []
    return [Signal(
        family="semantic",
        name="coordination_semantics",
        score=min(0.85, 0.20 + 0.16 * len(hits)),
        observation_ids=[observation.source_event_id],
        evidence=hits,
    )]
