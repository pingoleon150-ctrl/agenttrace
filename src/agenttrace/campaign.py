from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from agenttrace.collectors.base import Collector
from agenttrace.collectors.github import GitHubCodeSearchCollector, GitHubThreadSearchCollector
from agenttrace.collectors.grepapp import GrepAppCollector
from agenttrace.config import Settings
from agenttrace.models import EvidenceBundle, Observation
from agenttrace.pipeline import analyze_observations
from agenttrace.storage.sqlite import SQLiteStore

CollectorFactory = Callable[[str], Collector]


@dataclass
class CampaignResult:
    queries: list[str]
    sources: list[str]
    observations: list[Observation] = field(default_factory=list)
    bundles: list[EvidenceBundle] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    def summary(self, top: int = 20) -> dict[str, Any]:
        reviewable = [bundle for bundle in self.bundles if bundle.score.reviewable]
        ranked = sorted(self.bundles, key=lambda bundle: bundle.score.score, reverse=True)
        return {
            "queries": len(self.queries),
            "sources": self.sources,
            "observations": len(self.observations),
            "clusters": len(self.bundles),
            "reviewable_clusters": len(reviewable),
            "errors": self.errors,
            "top_clusters": [
                {
                    "cluster_id": bundle.cluster_id,
                    "score": bundle.score.score,
                    "reviewable": bundle.score.reviewable,
                    "actors": bundle.actors,
                    "reasons": bundle.score.reasons,
                    "provenance": sorted(
                        {observation.provenance.url for observation in bundle.observations}
                    )[:10],
                }
                for bundle in ranked[:top]
            ],
        }


def load_queries(path: str | Path) -> list[str]:
    payload = yaml.safe_load(Path(path).read_text()) or {}
    families = payload.get("families")
    if not isinstance(families, dict):
        raise TypeError("query file must contain a 'families' mapping")

    queries: list[str] = []
    for values in families.values():
        if not isinstance(values, list):
            raise TypeError("each query family must contain a list")
        for value in values:
            if isinstance(value, str) and value.strip() and value not in queries:
                queries.append(value.strip())
    if not queries:
        raise ValueError("query file does not contain any queries")
    return queries


def build_factories(
    sources: list[str],
    settings: Settings,
    limit: int,
    threads: int,
    comments: int,
) -> dict[str, CollectorFactory]:
    available: dict[str, CollectorFactory] = {
        "github-thread": lambda query: GitHubThreadSearchCollector(
            query, threads=threads, comments_per_thread=comments, settings=settings
        ),
        "github-code": lambda query: GitHubCodeSearchCollector(
            query, limit=limit, settings=settings
        ),
        "grep": lambda query: GrepAppCollector(query, limit=limit, settings=settings),
    }
    unknown = sorted(set(sources) - available.keys())
    if unknown:
        raise ValueError(f"unknown campaign sources: {', '.join(unknown)}")
    return {source: available[source] for source in sources}


async def run_campaign(
    queries: list[str],
    factories: dict[str, CollectorFactory],
    store: SQLiteStore,
    threshold: float = 0.60,
    window_minutes: int = 60,
    concurrency: int = 2,
    retries: int = 2,
) -> CampaignResult:
    result = CampaignResult(queries=queries, sources=list(factories))
    seen: set[tuple[str, str | None]] = set()

    semaphore = asyncio.Semaphore(max(1, concurrency))
    jobs = [
        _collect_job(query, source, factory, semaphore, retries)
        for query in queries
        for source, factory in factories.items()
    ]
    for query, source, observations, error in await asyncio.gather(*jobs):
        if error:
            result.errors.append({"query": query, "source": source, "error": error})
        for observation in observations:
            key = (observation.provenance.url, observation.content_sha256)
            if key in seen:
                continue
            seen.add(key)
            normalized = _normalize_observation(observation, source, query)
            store.upsert_observation(normalized)
            result.observations.append(normalized)

    result.bundles = analyze_observations(
        result.observations, threshold=threshold, window_minutes=window_minutes
    )
    for bundle in result.bundles:
        store.save_bundle(bundle)
    return result


async def _collect_job(
    query: str,
    source: str,
    factory: CollectorFactory,
    semaphore: asyncio.Semaphore,
    retries: int,
) -> tuple[str, str, list[Observation], str | None]:
    for attempt in range(max(0, retries) + 1):
        observations: list[Observation] = []
        try:
            async with semaphore:
                collector = factory(query)
                async for observation in collector.collect():
                    observations.append(observation)
            return query, source, observations, None
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code in {403, 429}
            if not retryable or attempt >= retries:
                return query, source, observations, f"{type(exc).__name__}: {exc}"
            retry_after = exc.response.headers.get("retry-after")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
            await asyncio.sleep(min(delay, 30.0))
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            return query, source, observations, f"{type(exc).__name__}: {exc}"
    raise AssertionError("unreachable")


def _normalize_observation(observation: Observation, source: str, query: str) -> Observation:
    metadata = {
        **observation.metadata,
        "campaign_query": query,
        "campaign_source": source,
        "origin_source": observation.source,
    }
    return observation.model_copy(
        update={
            "source": "campaign",
            "source_event_id": f"{observation.source}:{observation.source_event_id}",
            "metadata": metadata,
        }
    )
