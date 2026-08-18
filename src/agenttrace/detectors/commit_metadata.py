from __future__ import annotations

import re
from collections import Counter, defaultdict
from itertools import pairwise

from agenttrace.models import Observation, Signal

GENERATED_DOMAIN_RE = re.compile(
    r"(?:noreply|users\.noreply\.github\.com|localdomain|localhost|invalid)$", re.IGNORECASE
)
VARIABLE_RE = re.compile(r"\b(?:[0-9a-f]{7,40}|\d+(?:\.\d+)*|#[0-9]+)\b", re.IGNORECASE)


def detect_commit_metadata_patterns(observations: list[Observation]) -> list[Signal]:
    pushes = [item for item in observations if item.event_type.casefold() == "pushevent"]
    if len(pushes) < 5:
        return []
    signals: list[Signal] = []
    signals.extend(_detect_machine_intervals(pushes))
    signals.extend(_detect_uniform_messages(pushes))
    signals.extend(_detect_shared_generated_domain(pushes))
    return signals


def _detect_machine_intervals(pushes: list[Observation]) -> list[Signal]:
    by_actor: dict[str, list[Observation]] = defaultdict(list)
    for item in pushes:
        by_actor[item.actor_key or item.actor.casefold()].append(item)
    matches: list[Observation] = []
    exact_gaps = 0
    gap_count = 0
    for items in by_actor.values():
        ordered = sorted(items, key=lambda item: item.event_time)
        for left, right in pairwise(ordered):
            seconds = (right.event_time - left.event_time).total_seconds()
            if seconds <= 0:
                continue
            gap_count += 1
            if seconds % 60 == 0 and seconds <= 6 * 3600:
                exact_gaps += 1
                matches.extend((left, right))
    fraction = exact_gaps / max(1, gap_count)
    if exact_gaps < 4 or fraction < 0.75:
        return []
    return [
        Signal(
            family="commit",
            name="machine_exact_commit_intervals",
            score=min(0.90, 0.55 + 0.35 * fraction),
            observation_ids=sorted({item.event_key or item.source_event_id for item in matches}),
            evidence=[f"exact_minute_gap_count={exact_gaps}", f"exact_gap_fraction={fraction:.2f}"],
            evidence_groups=["commit:timing"],
        )
    ]


def _detect_uniform_messages(pushes: list[Observation]) -> list[Signal]:
    messages = [
        str(message)
        for item in pushes
        for message in item.metadata.get("commit_messages", [])
        if str(message).strip()
    ]
    if len(messages) < 8:
        return []
    templates = [VARIABLE_RE.sub("<var>", " ".join(message.casefold().split())) for message in messages]
    dominant = Counter(templates).most_common(1)[0][1] / len(templates)
    if dominant < 0.70:
        return []
    return [
        Signal(
            family="commit",
            name="uniform_commit_message_template",
            score=min(0.88, 0.52 + 0.40 * dominant),
            observation_ids=[item.event_key or item.source_event_id for item in pushes],
            evidence=[f"commit_message_count={len(messages)}", f"dominant_template_fraction={dominant:.2f}"],
            evidence_groups=["commit:message_style"],
        )
    ]


def _detect_shared_generated_domain(pushes: list[Observation]) -> list[Signal]:
    domains: dict[str, set[str]] = defaultdict(set)
    ids: dict[str, list[str]] = defaultdict(list)
    for item in pushes:
        actor = item.actor_key or item.actor.casefold()
        for domain in item.metadata.get("author_email_domains", []):
            normalized = str(domain).casefold()
            if GENERATED_DOMAIN_RE.search(normalized):
                domains[normalized].add(actor)
                ids[normalized].append(item.event_key or item.source_event_id)
    shared = {domain: actors for domain, actors in domains.items() if len(actors) >= 3}
    if not shared:
        return []
    return [
        Signal(
            family="commit",
            name="shared_generated_author_domain",
            score=min(0.86, 0.62 + 0.05 * max(len(actors) for actors in shared.values())),
            observation_ids=sorted({event for domain in shared for event in ids[domain]}),
            evidence=[
                f"generated_domain_count={len(shared)}",
                f"max_actor_count={max(len(actors) for actors in shared.values())}",
            ],
            evidence_groups=["commit:author_domain"],
        )
    ]
