from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from agenttrace.models import Observation, Signal
from agenttrace.util import sha256_text

TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_-])[A-Za-z0-9][A-Za-z0-9_-]{10,62}[A-Za-z0-9](?![A-Za-z0-9_-])"
)
HEX_RE = re.compile(r"\b[a-fA-F0-9]{16,64}\b")


@dataclass(frozen=True)
class Artifact:
    kind: str
    value: str


def extract_artifacts(obs: Observation) -> set[Artifact]:
    artifacts: set[Artifact] = set()
    for url in obs.artifact_urls:
        if len(url) >= 16:
            artifacts.add(Artifact("url", url))
    for code in obs.code_blocks:
        if len(code) >= 20:
            artifacts.add(Artifact("code", sha256_text(code)))
    text = obs.text or ""
    for value in HEX_RE.findall(text):
        artifacts.add(Artifact("hex", value.lower()))
    for value in TOKEN_RE.findall(text):
        if any(c.isdigit() for c in value) or "_" in value or "-" in value:
            artifacts.add(Artifact("token", value))
    return artifacts


def detect_cross_actor_reuse(observations: list[Observation]) -> list[Signal]:
    seen: dict[Artifact, set[str]] = defaultdict(set)
    obs_ids: dict[Artifact, list[str]] = defaultdict(list)
    for obs in observations:
        for artifact in extract_artifacts(obs):
            seen[artifact].add(obs.actor)
            obs_ids[artifact].append(obs.source_event_id)

    reused = {artifact: actors for artifact, actors in seen.items() if len(actors) >= 2}
    if not reused:
        return []

    max_actors = max(len(actors) for actors in reused.values())
    score = min(1.0, 0.48 + 0.09 * len(reused) + 0.08 * (max_actors - 2))
    evidence = []
    ids: list[str] = []
    for artifact, actors in list(reused.items())[:20]:
        display = artifact.value if artifact.kind != "code" else artifact.value[:16]
        evidence.append(f"{artifact.kind}:{display}:actors={','.join(sorted(actors))}")
        ids.extend(obs_ids[artifact])
    return [
        Signal(
            family="artifact",
            name="cross_actor_rare_artifact_reuse",
            score=score,
            observation_ids=sorted(set(ids)),
            evidence=evidence,
        )
    ]
