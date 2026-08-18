from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from agenttrace.models import Observation, Signal

LOCAL_NEGATION_RE = re.compile(r"\b(?:do not|don't|not|never|no)\b[^.!?]{0,24}$", re.IGNORECASE)
DELEGATION_RE = re.compile(
    r"\b(?:delegate|assign(?:ed)?|you handle|take (?:this|the) task|please (?:run|check|do))\b",
    re.IGNORECASE,
)
ACK_RE = re.compile(
    r"\b(?:ack|acknowledged|accepted|claiming|received (?:the )?task|starting task)\b",
    re.IGNORECASE,
)
RESULT_RE = re.compile(
    r"\b(?:task (?:is )?(?:complete|completed|finished)|returning (?:the )?result|"
    r"report(?:ing)? back|result\s*[:=])\b",
    re.IGNORECASE,
)
STATE_OUT_RE = re.compile(
    r"\b(?:checkpoint (?:saved|created)|saved state|state transfer|continuation token)\b",
    re.IGNORECASE,
)
STATE_IN_RE = re.compile(
    r"\b(?:resume from|resuming (?:from|with)|continue from|loaded checkpoint)\b",
    re.IGNORECASE,
)
REFERENCE_RE = re.compile(
    r"\b(?:task(?:_id|-id| id)?|job_id|run_id|correlation_id|checkpoint|resume_token|"
    r"continuation_token|state_id)\s*[:=#-]?\s*[`\"']?([A-Za-z0-9][A-Za-z0-9._-]{3,63})",
    re.IGNORECASE,
)
REFERENCE_STOPWORDS = {"complete", "completed", "finished", "accepted", "result", "the", "this"}
HTML_DERIVATIVE_RE = re.compile(
    r"<(?:details|blockquote)\b[^>]*>.*?</(?:details|blockquote)>",
    re.IGNORECASE | re.DOTALL,
)
FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
MAX_REFERENCE_OCCURRENCES = 100
MAX_PATHS = 500
MAX_REPLY_DEPTH = 16


@dataclass(frozen=True)
class ExchangePath:
    kind: str
    left: Observation
    right: Observation
    link_type: str
    shared_refs: frozenset[str]


def detect_coordination_semantics(observation: Observation) -> list[Signal]:
    """Expose weak per-message acts for diagnostics; they never form a strong exchange."""
    acts = _acts(_clean_text(observation.text or ""))
    if not acts:
        return []
    return [
        Signal(
            family="semantic",
            name="isolated_coordination_speech_act",
            score=min(0.34, 0.18 + 0.05 * len(acts)),
            observation_ids=[_event_key(observation)],
            evidence=sorted(acts),
        )
    ]


def detect_coordination_exchange(observations: list[Observation]) -> list[Signal]:
    """Detect bounded, linked cross-actor task and state-transfer trajectories."""
    ordered = sorted(observations, key=lambda obs: obs.event_time)
    by_key = {_event_key(obs): obs for obs in ordered}
    cleaned = {_event_key(obs): _clean_text(obs.text or "") for obs in ordered}
    acts = {key: _acts(text) for key, text in cleaned.items()}
    refs = {key: _references(text) for key, text in cleaned.items()}
    parent = {
        key: obs.parent_key
        for key, obs in by_key.items()
        if obs.parent_key and obs.parent_key in by_key
    }
    ancestors = {key: _ancestors(key, parent) for key in by_key}

    reference_index: dict[str, set[str]] = defaultdict(set)
    for key, values in refs.items():
        for value in values:
            if len(reference_index[value]) < MAX_REFERENCE_OCCURRENCES:
                reference_index[value].add(key)

    paths: list[ExchangePath] = []
    paths.extend(
        _find_paths("delegate_result", "delegation", "result", ordered, acts, refs, reference_index, ancestors)
    )
    if len(paths) < MAX_PATHS:
        paths.extend(
            _find_paths(
                "checkpoint_resume",
                "state_out",
                "state_in",
                ordered,
                acts,
                refs,
                reference_index,
                ancestors,
                limit=MAX_PATHS - len(paths),
            )
        )
    if not paths:
        return []

    acknowledgement_by_path: dict[int, Observation] = {}
    verified_native = 0
    verified_cross_context = 0
    for index, path in enumerate(paths):
        acknowledgement = _find_acknowledgement(path, ordered, acts, refs, ancestors)
        if acknowledgement:
            acknowledgement_by_path[index] = acknowledgement
        if path.link_type == "native_reply" and (
            acknowledgement or path.kind == "checkpoint_resume"
        ):
            verified_native += 1
        elif path.link_type == "shared_reference" and (
            acknowledgement or path.kind == "checkpoint_resume"
        ):
            path_observations = [path.left, path.right]
            if acknowledgement:
                path_observations.append(acknowledgement)
            if len({_context_key(obs) for obs in path_observations}) >= 2:
                verified_cross_context += 1

    ids = {
        _event_key(observation)
        for path in paths
        for observation in (path.left, path.right)
    }
    ids.update(_event_key(obs) for obs in acknowledgement_by_path.values())
    kinds = {path.kind for path in paths}
    link_types = {path.link_type for path in paths}
    score = 0.78
    if "checkpoint_resume" in kinds:
        score = max(score, 0.90)
    if acknowledgement_by_path:
        score = max(score, 0.94)
    score = min(0.98, score + 0.02 * (len(paths) - 1))
    return [
        Signal(
            family="semantic",
            name="linked_coordination_exchange",
            score=score,
            observation_ids=sorted(ids),
            evidence_groups=[
                f"semantic:{path.kind}:{_event_key(path.left)}:{_event_key(path.right)}"
                for path in paths
            ],
            depends_on=["artifact"] if "shared_reference" in link_types else [],
            metadata={
                "path_count": len(paths),
                "distinct_acknowledgements": len(acknowledgement_by_path),
                "verified_native_trajectories": verified_native,
                "verified_cross_context_trajectories": verified_cross_context,
                "path_limit_reached": len(paths) >= MAX_PATHS,
            },
            evidence=[
                f"paths={len(paths)}",
                f"path_types={','.join(sorted(kinds))}",
                f"link_types={','.join(sorted(link_types))}",
                f"distinct_acknowledgements={len(acknowledgement_by_path)}",
                f"verified_native_trajectories={verified_native}",
                f"verified_cross_context_trajectories={verified_cross_context}",
            ],
        )
    ]


def _find_paths(
    kind: str,
    left_act: str,
    right_act: str,
    ordered: list[Observation],
    acts: dict[str, set[str]],
    refs: dict[str, set[str]],
    reference_index: dict[str, set[str]],
    ancestors: dict[str, set[str]],
    limit: int = MAX_PATHS,
) -> list[ExchangePath]:
    left_keys = {_event_key(obs) for obs in ordered if left_act in acts[_event_key(obs)]}
    by_key = {_event_key(obs): obs for obs in ordered}
    result: list[ExchangePath] = []
    seen: set[tuple[str, str]] = set()
    for right in ordered:
        right_key = _event_key(right)
        if right_act not in acts[right_key]:
            continue
        candidates = set(ancestors[right_key]) & left_keys
        for reference in refs[right_key]:
            candidates.update(reference_index.get(reference, set()) & left_keys)
        for left_key in sorted(candidates):
            left = by_key[left_key]
            pair = (left_key, right_key)
            if (
                pair in seen
                or left.event_time > right.event_time
                or _actor_identity(left) == _actor_identity(right)
            ):
                continue
            shared = frozenset(refs[left_key] & refs[right_key])
            link_type = "native_reply" if left_key in ancestors[right_key] else "shared_reference"
            if link_type == "shared_reference" and not shared:
                continue
            seen.add(pair)
            result.append(ExchangePath(kind, left, right, link_type, shared))
            if len(result) >= limit:
                return result
    return result


def _find_acknowledgement(
    path: ExchangePath,
    ordered: list[Observation],
    acts: dict[str, set[str]],
    refs: dict[str, set[str]],
    ancestors: dict[str, set[str]],
) -> Observation | None:
    left_key = _event_key(path.left)
    right_key = _event_key(path.right)
    for candidate in ordered:
        candidate_key = _event_key(candidate)
        if (
            candidate_key in {left_key, right_key}
            or "ack" not in acts[candidate_key]
            or not (path.left.event_time < candidate.event_time < path.right.event_time)
            or _actor_identity(candidate) != _actor_identity(path.right)
        ):
            continue
        if path.link_type == "native_reply":
            if left_key in ancestors[candidate_key] and (
                candidate_key in ancestors[right_key] or left_key in ancestors[right_key]
            ):
                return candidate
        elif path.shared_refs & refs[candidate_key]:
            return candidate
    return None


def _ancestors(event_key: str, parent: dict[str, str]) -> set[str]:
    result: set[str] = set()
    current = event_key
    for _ in range(MAX_REPLY_DEPTH):
        current = parent.get(current, "")
        if not current or current in result:
            break
        result.add(current)
    return result


def _acts(text: str) -> set[str]:
    if not text:
        return set()
    patterns = {
        "delegation": DELEGATION_RE,
        "ack": ACK_RE,
        "result": RESULT_RE,
        "state_out": STATE_OUT_RE,
        "state_in": STATE_IN_RE,
    }
    return {name for name, pattern in patterns.items() if _has_unnegated_match(pattern, text)}


def _references(text: str) -> set[str]:
    references = set()
    for match in REFERENCE_RE.finditer(text):
        value = match.group(1).lower().rstrip(".,;)]}`\"'")
        if value not in REFERENCE_STOPWORDS:
            references.add(value)
    return references


def _clean_text(text: str) -> str:
    text = HTML_DERIVATIVE_RE.sub("", text)
    text = FENCED_CODE_RE.sub("", text)
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">"))


def _has_unnegated_match(pattern: re.Pattern[str], text: str) -> bool:
    for match in pattern.finditer(text):
        prefix = text[max(0, match.start() - 32) : match.start()]
        if not LOCAL_NEGATION_RE.search(prefix):
            return True
    return False


def _actor_identity(observation: Observation) -> str:
    return observation.actor.strip().casefold()


def _event_key(observation: Observation) -> str:
    return observation.event_key or f"{observation.source}:{observation.source_event_id}"


def _context_key(observation: Observation) -> str:
    return (
        observation.conversation_key
        or observation.resource_key
        or observation.event_key
        or observation.source_event_id
    )
