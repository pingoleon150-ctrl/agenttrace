from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from agenttrace import __version__
from agenttrace.collectors.base import Collector
from agenttrace.collectors.github import GitHubCodeSearchCollector, GitHubThreadSearchCollector
from agenttrace.collectors.grepapp import GrepAppCollector
from agenttrace.config import Settings
from agenttrace.ledger import RepositoryLedger, update_ledger
from agenttrace.models import EvidenceBundle, Observation
from agenttrace.pipeline import analyze_observations
from agenttrace.storage.sqlite import SQLiteStore
from agenttrace.util import utcnow

CollectorFactory = Callable[[str, int], Collector]


@dataclass
class CampaignResult:
    queries: list[str]
    sources: list[str]
    observations: list[Observation] = field(default_factory=list)
    bundles: list[EvidenceBundle] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    search_pages: list[dict[str, Any]] = field(default_factory=list)

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
            "search_pages": self.search_pages,
            "top_clusters": [
                {
                    "cluster_id": bundle.cluster_id,
                    "score": bundle.score.score,
                    "priority_score": bundle.score.score,
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
    repository_allowed: Callable[[str], bool] | None = None,
) -> dict[str, CollectorFactory]:
    available: dict[str, CollectorFactory] = {
        "github-thread": lambda query, page: GitHubThreadSearchCollector(
            query,
            threads=threads,
            comments_per_thread=comments,
            settings=settings,
            repository_allowed=repository_allowed,
            start_page=page,
        ),
        "github-code": lambda query, page: GitHubCodeSearchCollector(
            query, limit=limit, settings=settings, start_page=page
        ),
        "grep": lambda query, page: GrepAppCollector(
            query, limit=limit, settings=settings, start_page=page
        ),
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
    repository_allowed: Callable[[str], bool] | None = None,
    ledger: RepositoryLedger | None = None,
    rotate_pages: bool = False,
    page_limits: dict[str, int] | None = None,
    page_steps: dict[str, int] | None = None,
) -> CampaignResult:
    result = CampaignResult(queries=queries, sources=list(factories))
    seen: set[tuple[str, str | None]] = set()

    semaphore = asyncio.Semaphore(max(1, concurrency))
    jobs = []
    for query in queries:
        for source, factory in factories.items():
            maximum = (page_limits or {}).get(source, 1)
            page = store.discovery_page(source, query, maximum) if rotate_pages else 1
            jobs.append(_collect_job(query, source, page, factory, semaphore, retries))
    for query, source, page, observations, error, exhausted in await asyncio.gather(*jobs):
        result.search_pages.append({"query": query, "source": source, "page": page})
        if error:
            result.errors.append({"query": query, "source": source, "error": error})
        elif rotate_pages:
            updated_at = utcnow().isoformat()
            if exhausted:
                store.reset_discovery_page(source, query, updated_at)
            else:
                store.advance_discovery_page(
                    source,
                    query,
                    page,
                    (page_limits or {}).get(source, 1),
                    updated_at,
                    (page_steps or {}).get(source, 1),
                )
        for observation in observations:
            if (
                observation.repository
                and repository_allowed
                and not repository_allowed(observation.repository)
            ):
                continue
            key = (observation.provenance.url, observation.content_sha256)
            if key in seen:
                continue
            seen.add(key)
            fingerprint = f"{key[0]}\0{key[1] or ''}"
            if not store.claim_fingerprint(fingerprint, observation.observed_at.isoformat()):
                continue
            normalized = _normalize_observation(observation, source, query)
            store.upsert_observation(normalized)
            result.observations.append(normalized)

    result.bundles = analyze_observations(
        result.observations, threshold=threshold, window_minutes=window_minutes
    )
    for bundle in result.bundles:
        store.save_bundle(bundle)
    if ledger:
        update_ledger(ledger, result.observations, result.bundles, queries, __version__)
    return result


async def _collect_job(
    query: str,
    source: str,
    page: int,
    factory: CollectorFactory,
    semaphore: asyncio.Semaphore,
    retries: int,
) -> tuple[str, str, int, list[Observation], str | None, bool]:
    for attempt in range(max(0, retries) + 1):
        observations: list[Observation] = []
        try:
            async with semaphore:
                collector = factory(query, page)
                async for observation in collector.collect():
                    observations.append(observation)
            exhausted = bool(getattr(collector, "exhausted", False))
            return query, source, page, observations, None, exhausted
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code in {403, 429} or (
                500 <= exc.response.status_code < 600
            )
            if not retryable or attempt >= retries:
                return query, source, page, observations, f"{type(exc).__name__}: {exc}", False
            retry_after = exc.response.headers.get("retry-after")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
            await asyncio.sleep(min(delay, 30.0))
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            return query, source, page, observations, f"{type(exc).__name__}: {exc}", False
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
