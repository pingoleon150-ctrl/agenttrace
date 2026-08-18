from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

from agenttrace import __version__
from agenttrace.calibration import CalibrationProfile
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
    watchlist: list[dict] | None = None

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "observations": self.observations,
            "clusters": self.clusters,
            "alert": self.alert,
            "queries": self.queries,
            "search_pages": self.search_pages or [],
            "errors": self.errors or [],
            "watchlist": self.watchlist or [],
        }


def take_watch_query_batch(
    store: SQLiteStore, queries: list[str], batch_size: int
) -> list[str]:
    """Advance the query cursor only when source collection is not paused."""
    if store.pending_alert():
        return []
    return store.take_query_batch(queries, batch_size)


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
    history_limit: int = 20_000,
    window_minutes: int = 1_440,
    calibration: CalibrationProfile | None = None,
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
        calibration=calibration,
    )
    history = store.list_observations(max(1, history_limit))
    bundles = analyze_observations(
        history,
        threshold=threshold,
        window_minutes=max(1, window_minutes),
        calibration=calibration,
    )
    if ledger:
        update_ledger(
            ledger, campaign.observations, bundles, ledger_queries or queries, __version__
        )
    new_event_keys = {obs.event_key for obs in campaign.observations}
    candidates = [
        bundle
        for bundle in bundles
        if bundle.score.reviewable
        and any(obs.event_key in new_event_keys for obs in bundle.observations)
    ]
    if not candidates:
        watchlist = [
            _public_bundle(bundle)
            for bundle in sorted(bundles, key=lambda item: item.score.score, reverse=True)
            if not bundle.score.reviewable and bundle.score.score > 0
        ][:5]
        return WatchResult(
            state="watching",
            observations=len(campaign.observations),
            clusters=len(bundles),
            queries=len(queries),
            search_pages=campaign.search_pages,
            errors=campaign.errors,
            watchlist=watchlist,
        )

    bundle = max(candidates, key=lambda item: item.score.score)
    fingerprint = hashlib.sha256(
        "\n".join(sorted(obs.provenance.url for obs in bundle.observations)).encode()
    ).hexdigest()
    summary = json.dumps(
        {
            "cluster_id": bundle.cluster_id,
            "score": bundle.score.score,
            "priority_score": bundle.score.score,
            "confidence": bundle.score.confidence,
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


def _public_bundle(bundle) -> dict:
    return {
        "cluster_id": bundle.cluster_id,
        "score": bundle.score.score,
        "priority_score": bundle.score.score,
        "confidence": bundle.score.confidence,
        "actors": bundle.actors,
        "reasons": bundle.score.reasons,
        "provenance": sorted({obs.provenance.url for obs in bundle.observations})[:5],
    }
