from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

from agenttrace.campaign import CollectorFactory, run_campaign
from agenttrace.ledger import RepositoryLedger, update_ledger
from agenttrace.pipeline import analyze_observations
from agenttrace.storage.sqlite import SQLiteStore


@dataclass
class WatchResult:
    state: str
    observations: int = 0
    clusters: int = 0
    alert: dict | None = None
    queries: int = 0
    search_pages: list[dict] | None = None
    errors: list[dict[str, str]] | None = None

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "observations": self.observations,
            "clusters": self.clusters,
            "alert": self.alert,
            "queries": self.queries,
            "search_pages": self.search_pages or [],
            "errors": self.errors or [],
        }


async def watch_cycle(
    queries: list[str],
    factories: dict[str, CollectorFactory],
    store: SQLiteStore,
    threshold: float = 0.75,
    concurrency: int = 2,
    retries: int = 2,
    repository_allowed: Callable[[str], bool] | None = None,
    ledger: RepositoryLedger | None = None,
    ledger_queries: list[str] | None = None,
    page_limits: dict[str, int] | None = None,
    page_steps: dict[str, int] | None = None,
) -> WatchResult:
    pending = store.pending_alert()
    if pending:
        return WatchResult(state="paused", alert=_public_alert(pending))

    campaign = await run_campaign(
        queries,
        factories,
        store,
        threshold=threshold,
        concurrency=concurrency,
        retries=retries,
        repository_allowed=repository_allowed,
        rotate_pages=True,
        page_limits=page_limits,
        page_steps=page_steps,
    )
    repositories = {obs.repository for obs in campaign.observations if obs.repository}
    history = store.observations_for_repositories(repositories)
    bundles = analyze_observations(history, threshold=threshold)
    if ledger:
        update_ledger(
            ledger, campaign.observations, bundles, ledger_queries or queries, "0.2.0"
        )
    candidates = [bundle for bundle in bundles if bundle.score.reviewable]
    if not candidates:
        return WatchResult(
            state="watching",
            observations=len(campaign.observations),
            clusters=len(bundles),
            queries=len(queries),
            search_pages=campaign.search_pages,
            errors=campaign.errors,
        )

    bundle = max(candidates, key=lambda item: item.score.score)
    fingerprint = hashlib.sha256(
        "\n".join(sorted(obs.provenance.url for obs in bundle.observations)).encode()
    ).hexdigest()
    summary = json.dumps(
        {
            "cluster_id": bundle.cluster_id,
            "score": bundle.score.score,
            "actors": bundle.actors,
            "reasons": bundle.score.reasons,
            "provenance": sorted({obs.provenance.url for obs in bundle.observations})[:20],
            "warning": "Candidate for human review; not proof of autonomous-agent activity.",
        },
        indent=2,
    )
    alert_id = store.create_alert(fingerprint, summary, bundle)
    return WatchResult(
        state="paused",
        observations=len(campaign.observations),
        clusters=len(bundles),
        alert={"id": alert_id, "status": "pending", "summary": summary},
        queries=len(queries),
        search_pages=campaign.search_pages,
        errors=campaign.errors,
    )


def _public_alert(alert: dict) -> dict:
    return {"id": alert["id"], "status": alert["status"], "summary": alert["summary"]}
