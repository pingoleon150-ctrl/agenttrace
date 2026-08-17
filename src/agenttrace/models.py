from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Provenance(BaseModel):
    url: str
    retrieval_method: str | None = None
    retrieved_at: datetime | None = None


class Observation(BaseModel):
    source: str
    source_event_id: str
    observed_at: datetime
    event_time: datetime
    actor: str
    event_type: str
    text: str | None = None
    repository: str | None = None
    thread_id: str | None = None
    reply_to: str | None = None
    artifact_urls: list[str] = Field(default_factory=list)
    code_blocks: list[str] = Field(default_factory=list)
    content_sha256: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance


class Signal(BaseModel):
    family: str
    name: str
    score: float = Field(ge=0.0, le=1.0)
    observation_ids: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class ClusterScore(BaseModel):
    score: float
    families: dict[str, float]
    reviewable: bool
    actor_count: int
    observation_count: int
    reasons: list[str] = Field(default_factory=list)


class EvidenceBundle(BaseModel):
    cluster_id: str
    created_at: datetime
    actors: list[str]
    observations: list[Observation]
    signals: list[Signal]
    score: ClusterScore
    uncertainty: str
