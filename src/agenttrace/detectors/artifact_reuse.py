from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from agenttrace.models import Observation, Signal
from agenttrace.util import sha256_text

COORDINATION_KEYS = (
    "task_id",
    "task-id",
    "job_id",
    "worker_id",
    "run_id",
    "message_id",
    "correlation_id",
    "nonce",
    "checkpoint",
    "resume_token",
    "continuation_token",
    "state_id",
    "lease_id",
)
KEYED_VALUE_RE = re.compile(
    rf"\b(?P<key>{'|'.join(re.escape(key) for key in COORDINATION_KEYS)})\b"
    r"\s*[:=#]\s*[`\"']?(?P<value>[A-Za-z0-9][A-Za-z0-9._:/+=-]{5,127})",
    re.IGNORECASE,
)
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
HASH_RE = re.compile(r"^[0-9a-f]{7,64}$", re.IGNORECASE)
PLACEHOLDERS = {
    "example",
    "placeholder",
    "your-token-here",
    "xxxxxxxx",
    "00000000",
    "12345678",
    "task-1234",
}
TRACKING_PARAMETERS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}
COMMON_URL_HOSTS = {"github.com", "www.github.com", "docs.github.com"}


@dataclass(frozen=True)
class Artifact:
    kind: str
    value: str


def extract_artifacts(obs: Observation) -> set[Artifact]:
    """Extract typed coordination artifacts, never arbitrary hashes or long identifiers."""
    artifacts: set[Artifact] = set()
    for url in obs.artifact_urls:
        normalized = _normalize_external_url(url)
        if normalized:
            artifacts.add(Artifact("external_url", normalized))
    for code in obs.code_blocks:
        canonical = _canonical_code(code)
        if canonical:
            artifacts.add(Artifact("code", sha256_text(canonical)))

    text = _strip_markdown_quotes(obs.text or "")
    for match in KEYED_VALUE_RE.finditer(text):
        key = match.group("key").lower().replace("-", "_")
        value = match.group("value").rstrip(".,;)]}`\"'")
        if _valid_keyed_value(value):
            artifacts.add(Artifact(f"marker:{key}", value.lower()))
    return artifacts


def detect_cross_actor_reuse(observations: list[Observation]) -> list[Signal]:
    seen: dict[Artifact, set[str]] = defaultdict(set)
    obs_ids: dict[Artifact, list[str]] = defaultdict(list)
    contexts: dict[Artifact, set[str]] = defaultdict(set)
    for obs in observations:
        for artifact in extract_artifacts(obs):
            seen[artifact].add(obs.actor_key or f"{obs.platform}:actor:{obs.actor.lower()}")
            obs_ids[artifact].append(obs.event_key or obs.source_event_id)
            contexts[artifact].add(
                obs.conversation_key or obs.resource_key or obs.event_key or obs.source_event_id
            )

    reused = {artifact: actors for artifact, actors in seen.items() if len(actors) >= 2}
    if not reused:
        return []

    strongest = max(_artifact_strength(artifact, contexts[artifact]) for artifact in reused)
    if strongest < 0.55:
        return []
    max_actors = max(len(actors) for actors in reused.values())
    score = min(0.98, strongest + 0.04 * (max_actors - 2) + 0.03 * (len(reused) - 1))
    evidence = []
    evidence_groups = []
    ids: list[str] = []
    for artifact, actors in sorted(reused.items(), key=lambda item: (item[0].kind, item[0].value))[
        :20
    ]:
        digest = sha256_text(artifact.value)[:16]
        evidence.append(
            f"{artifact.kind}:sha256={digest}:actors={len(actors)}:contexts={len(contexts[artifact])}"
        )
        evidence_groups.append(f"artifact:{digest}")
        ids.extend(obs_ids[artifact])
    return [
        Signal(
            family="artifact",
            name="cross_actor_typed_artifact_reuse",
            score=score,
            observation_ids=sorted(set(ids)),
            evidence=evidence,
            evidence_groups=evidence_groups,
        )
    ]


def _artifact_strength(artifact: Artifact, contexts: set[str]) -> float:
    independent_contexts = len(contexts)
    if artifact.kind.startswith("marker:"):
        value = artifact.value
        if UUID_RE.fullmatch(value) or HASH_RE.fullmatch(value):
            base = 0.58
        else:
            base = 0.82
    elif artifact.kind == "code":
        base = 0.66
    else:
        base = 0.56
    return min(0.95, base + 0.08 * max(0, independent_contexts - 1))


def _valid_keyed_value(value: str) -> bool:
    lowered = value.lower()
    return not (lowered in PLACEHOLDERS or len(set(lowered)) < 4 or lowered.isdigit())


def _strip_markdown_quotes(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">"))


def _canonical_code(value: str) -> str | None:
    canonical = "\n".join(line.rstrip() for line in value.strip().splitlines())
    if len(canonical) < 120 or len(set(canonical)) < 12:
        return None
    return canonical


def _normalize_external_url(value: str) -> str | None:
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https"} or not host or host in COMMON_URL_HOSTS:
        return None
    query = urlencode(
        [(key, item) for key, item in parse_qsl(parts.query) if key.lower() not in TRACKING_PARAMETERS]
    )
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ""))
