from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class Provenance(BaseModel):
    url: str
    retrieval_method: str | None = None
    retrieved_at: datetime | None = None


class Observation(BaseModel):
    source: str
    source_event_id: str
    event_key: str | None = None
    observed_at: datetime
    event_time: datetime
    actor: str
    platform: str | None = None
    actor_key: str | None = None
    event_type: str
    text: str | None = None
    repository: str | None = None
    resource_key: str | None = None
    thread_id: str | None = None
    conversation_key: str | None = None
    reply_to: str | None = None
    parent_key: str | None = None
    artifact_urls: list[str] = Field(default_factory=list)
    code_blocks: list[str] = Field(default_factory=list)
    content_sha256: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance

    @model_validator(mode="after")
    def add_namespaced_keys(self) -> Observation:
        origin_source = str(self.metadata.get("origin_source") or self.source)
        campaign_source = str(self.metadata.get("campaign_source") or "")
        platform = self.platform or _infer_platform(origin_source, campaign_source)
        self.platform = platform
        self.actor_key = self.actor_key or f"{platform}:actor:{self.actor.lower()}"
        self.event_key = self.event_key or f"{platform}:event:{self.source}:{self.source_event_id}"
        if self.repository and not self.resource_key:
            self.resource_key = f"{platform}:repository:{self.repository.lower()}"
        if self.thread_id and self.resource_key and not self.conversation_key:
            self.conversation_key = f"{self.resource_key}:thread:{self.thread_id}"
        if self.reply_to and not self.parent_key:
            self.parent_key = f"{platform}:event:{self.source}:{self.reply_to}"
        return self


class Signal(BaseModel):
    family: str
    name: str
    score: float = Field(ge=0.0, le=1.0)
    observation_ids: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    evidence_groups: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClusterScore(BaseModel):
    score: float
    families: dict[str, float]
    confidence: Literal["low", "medium", "high"] = "low"
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


def _infer_platform(source: str, campaign_source: str = "") -> str:
    lowered = source.lower()
    campaign_lowered = campaign_source.lower()
    if (
        "github" in lowered
        or lowered in {"gharchive", "grepapp"}
        or campaign_lowered in {"github-thread", "github-code", "grep"}
    ):
        return "github"
    return lowered
