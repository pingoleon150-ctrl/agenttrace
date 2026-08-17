from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta

from agenttrace.campaign import build_factories, load_queries, run_campaign
from agenttrace.collectors.gharchive import GHArchiveHourCollector
from agenttrace.collectors.github import (
    GitHubCodeSearchCollector,
    GitHubIssueSearchCollector,
    GitHubPublicEventsCollector,
    GitHubThreadSearchCollector,
)
from agenttrace.collectors.grepapp import GrepAppCollector
from agenttrace.collectors.jsonl import JsonlCollector
from agenttrace.config import Settings
from agenttrace.ledger import RepositoryLedger, update_ledger
from agenttrace.models import Observation, Provenance
from agenttrace.monitor import watch_cycle
from agenttrace.pipeline import analyze_cluster, analyze_observations, collect_to_store
from agenttrace.storage.sqlite import SQLiteStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agenttrace", description="Detect public agent-coordination patterns"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("demo", help="Run a deterministic synthetic coordination demo")

    p = sub.add_parser("github-search", help="Search public GitHub issues and pull requests")
    p.add_argument("--query", required=True)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--threshold", type=float, default=0.60)

    p = sub.add_parser(
        "github-thread-search", help="Search GitHub and expand candidate issue/PR conversations"
    )
    p.add_argument("--query", required=True)
    p.add_argument("--threads", type=int, default=20)
    p.add_argument("--comments", type=int, default=100)
    p.add_argument("--threshold", type=float, default=0.60)

    p = sub.add_parser("github-code-search", help="Search public GitHub code (requires token)")
    p.add_argument("--query", required=True)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--threshold", type=float, default=0.60)

    p = sub.add_parser("github-events", help="Collect recent GitHub public events")
    p.add_argument("--pages", type=int, default=1)
    p.add_argument("--threshold", type=float, default=0.60)

    p = sub.add_parser(
        "grep-search", help="Search public code using the experimental grep.app adapter"
    )
    p.add_argument("--query", required=True)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--threshold", type=float, default=0.60)

    p = sub.add_parser("gharchive-hour", help="Replay one GH Archive hourly file")
    p.add_argument("--hour", required=True, help="YYYY-MM-DDTHH or YYYY-MM-DD-HH in UTC")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--threshold", type=float, default=0.60)

    p = sub.add_parser("analyze-jsonl", help="Analyze a canonical Observation JSONL file")
    p.add_argument("path")
    p.add_argument("--threshold", type=float, default=0.60)

    p = sub.add_parser(
        "export-reviewable", help="Print reviewable evidence bundles from current DB"
    )
    p.add_argument("--limit", type=int, default=10000)
    p.add_argument("--threshold", type=float, default=0.60)

    p = sub.add_parser("campaign", help="Run a multi-query, multi-source discovery campaign")
    p.add_argument("--queries", default="queries/seed_queries.yaml")
    p.add_argument(
        "--sources",
        default="github-thread,github-code,grep",
        help="Comma-separated: github-thread, github-code, grep",
    )
    p.add_argument("--limit", type=int, default=20, help="Maximum code hits per query/source")
    p.add_argument("--threads", type=int, default=5, help="GitHub threads per query")
    p.add_argument("--comments", type=int, default=50, help="Comments expanded per thread")
    p.add_argument("--threshold", type=float, default=0.60)
    p.add_argument("--window-minutes", type=int, default=60)
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--retries", type=int, default=2)
    p.add_argument("--top", type=int, default=20)
    _add_ledger_arguments(p)

    p = sub.add_parser(
        "watch", help="Continuously discover new evidence and pause on a high-confidence candidate"
    )
    p.add_argument("--queries", default="queries/seed_queries.yaml")
    p.add_argument("--sources", default="github-thread,github-code,grep")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--threads", type=int, default=5)
    p.add_argument("--comments", type=int, default=50)
    p.add_argument("--threshold", type=float, default=0.75)
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--retries", type=int, default=2)
    p.add_argument("--interval", type=int, default=300)
    p.add_argument(
        "--query-batch-size",
        type=int,
        default=2,
        help="Queries rotated per cycle; cursors persist in SQLite",
    )
    p.add_argument("--once", action="store_true")
    _add_ledger_arguments(p)

    p = sub.add_parser("review-alert", help="Resolve a paused monitor alert")
    p.add_argument("alert_id", type=int)
    p.add_argument("--status", choices=["reviewed", "false-positive", "escalated"], required=True)

    p = sub.add_parser(
        "export-ledger", help="Export analyzed repositories from SQLite to the shared ledger"
    )
    p.add_argument("--queries", default="queries/seed_queries.yaml")
    p.add_argument("--ledger", default="ledger/repos")
    p.add_argument("--limit", type=int, default=100000)
    p.add_argument("--threshold", type=float, default=0.75)

    return parser


def _add_ledger_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ledger", default="ledger/repos")
    parser.add_argument("--recheck-repository", action="append", default=[])
    parser.add_argument("--recheck-stale", type=int, metavar="DAYS")
    parser.add_argument("--recheck-all", action="store_true")


def _repository_policy(args):
    ledger = RepositoryLedger(args.ledger)
    requested = set(args.recheck_repository)

    def allowed(repository: str) -> bool:
        return not ledger.should_skip(
            repository,
            recheck_all=args.recheck_all,
            recheck_repositories=requested,
            recheck_stale_days=args.recheck_stale,
        )

    return ledger, allowed


async def _run_collector(collector, threshold: float) -> int:
    settings = Settings.from_env()
    with SQLiteStore(settings.db_path) as store:
        observations = await collect_to_store(collector, store)
        bundles = analyze_observations(observations, threshold=threshold)
        for bundle in bundles:
            store.save_bundle(bundle)
        _print_summary(observations, bundles)
    return 0


def _print_summary(observations, bundles) -> None:
    reviewable = [b for b in bundles if b.score.reviewable]
    result = {
        "observations": len(observations),
        "clusters": len(bundles),
        "reviewable_clusters": len(reviewable),
        "top_clusters": [
            {
                "cluster_id": b.cluster_id,
                "score": b.score.score,
                "reviewable": b.score.reviewable,
                "actors": b.actors,
                "reasons": b.score.reasons,
                "provenance": [o.provenance.url for o in b.observations[:10]],
            }
            for b in sorted(bundles, key=lambda x: x.score.score, reverse=True)[:20]
        ],
    }
    print(json.dumps(result, indent=2))


def _demo() -> int:
    t0 = datetime.now(UTC)
    common_artifact = "artifact-7f9c2a11-checkpoint-8891"
    observations = [
        Observation(
            source="demo",
            source_event_id="1",
            observed_at=t0,
            event_time=t0,
            actor="coord",
            event_type="post",
            text=f"TASK-ID: probe-991 delegate worker. nonce={common_artifact}",
            repository="demo/swarm",
            thread_id="42",
            code_blocks=[common_artifact],
            provenance=Provenance(url="https://example.invalid/1"),
        ),
        Observation(
            source="demo",
            source_event_id="2",
            observed_at=t0,
            event_time=t0 + timedelta(seconds=8),
            actor="worker-a",
            event_type="reply",
            text=f"ACK task probe-991 seq=2 {common_artifact}",
            repository="demo/swarm",
            thread_id="42",
            reply_to="1",
            code_blocks=[common_artifact],
            provenance=Provenance(url="https://example.invalid/2"),
        ),
        Observation(
            source="demo",
            source_event_id="3",
            observed_at=t0,
            event_time=t0 + timedelta(seconds=17),
            actor="coord",
            event_type="reply",
            text="heartbeat worker alive retry_count=1 checkpoint",
            repository="demo/swarm",
            thread_id="42",
            reply_to="2",
            provenance=Provenance(url="https://example.invalid/3"),
        ),
        Observation(
            source="demo",
            source_event_id="4",
            observed_at=t0,
            event_time=t0 + timedelta(seconds=25),
            actor="worker-a",
            event_type="reply",
            text="ACK result completed report back",
            repository="demo/swarm",
            thread_id="42",
            reply_to="3",
            provenance=Provenance(url="https://example.invalid/4"),
        ),
    ]
    bundle = analyze_cluster("demo:swarm:42", observations, threshold=0.50)
    print(bundle.model_dump_json(indent=2))
    return 0


async def _run_campaign(args) -> int:
    settings = Settings.from_env()
    queries = load_queries(args.queries)
    sources = [source.strip() for source in args.sources.split(",") if source.strip()]
    ledger, repository_allowed = _repository_policy(args)
    factories = build_factories(
        sources,
        settings,
        limit=args.limit,
        threads=args.threads,
        comments=args.comments,
        repository_allowed=repository_allowed,
    )
    with SQLiteStore(settings.db_path) as store:
        result = await run_campaign(
            queries,
            factories,
            store,
            threshold=args.threshold,
            window_minutes=args.window_minutes,
            concurrency=args.concurrency,
            retries=args.retries,
            repository_allowed=repository_allowed,
            ledger=ledger,
        )
    print(json.dumps(result.summary(top=args.top), indent=2))
    return 1 if result.errors and not result.observations else 0


async def _watch(args) -> int:
    settings = Settings.from_env()
    all_queries = load_queries(args.queries)
    sources = [source.strip() for source in args.sources.split(",") if source.strip()]
    ledger, repository_allowed = _repository_policy(args)
    factories = build_factories(
        sources,
        settings,
        limit=args.limit,
        threads=args.threads,
        comments=args.comments,
        repository_allowed=repository_allowed,
    )
    code_page_size = min(100, max(1, args.limit))
    page_limits = {
        "github-thread": max(1, 1000 // max(1, args.threads)),
        "github-code": max(1, 1000 // code_page_size),
        "grep": 100,
    }
    page_steps = {
        "github-thread": 1,
        "github-code": max(1, (args.limit + 99) // 100),
        "grep": max(1, (args.limit + 9) // 10),
    }
    while True:
        with SQLiteStore(settings.db_path) as store:
            queries = store.take_query_batch(all_queries, args.query_batch_size)
            result = await watch_cycle(
                queries,
                factories,
                store,
                threshold=args.threshold,
                concurrency=args.concurrency,
                retries=args.retries,
                repository_allowed=repository_allowed,
                ledger=ledger,
                ledger_queries=all_queries,
                page_limits=page_limits,
                page_steps=page_steps,
            )
        print(json.dumps(result.as_dict(), indent=2), flush=True)
        if result.state == "paused" or args.once:
            return 2 if result.state == "paused" else 0
        await asyncio.sleep(max(1, args.interval))


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "demo":
        return _demo()
    if args.command == "github-search":
        return asyncio.run(
            _run_collector(GitHubIssueSearchCollector(args.query, args.limit), args.threshold)
        )
    if args.command == "github-thread-search":
        return asyncio.run(
            _run_collector(
                GitHubThreadSearchCollector(args.query, args.threads, args.comments), args.threshold
            )
        )
    if args.command == "github-code-search":
        return asyncio.run(
            _run_collector(GitHubCodeSearchCollector(args.query, args.limit), args.threshold)
        )
    if args.command == "github-events":
        return asyncio.run(_run_collector(GitHubPublicEventsCollector(args.pages), args.threshold))
    if args.command == "grep-search":
        return asyncio.run(_run_collector(GrepAppCollector(args.query, args.limit), args.threshold))
    if args.command == "gharchive-hour":
        return asyncio.run(
            _run_collector(GHArchiveHourCollector(args.hour, args.limit), args.threshold)
        )
    if args.command == "analyze-jsonl":
        return asyncio.run(_run_collector(JsonlCollector(args.path), args.threshold))
    if args.command == "export-reviewable":
        settings = Settings.from_env()
        with SQLiteStore(settings.db_path) as store:
            observations = store.list_observations(args.limit)
            bundles = analyze_observations(observations, threshold=args.threshold)
            for bundle in bundles:
                if bundle.score.reviewable:
                    print(bundle.model_dump_json())
        return 0
    if args.command == "campaign":
        return asyncio.run(_run_campaign(args))
    if args.command == "watch":
        return asyncio.run(_watch(args))
    if args.command == "review-alert":
        settings = Settings.from_env()
        with SQLiteStore(settings.db_path) as store:
            resolved = store.resolve_alert(
                args.alert_id, args.status, datetime.now(UTC).isoformat()
            )
        print(json.dumps({"alert_id": args.alert_id, "status": args.status, "resolved": resolved}))
        return 0 if resolved else 1
    if args.command == "export-ledger":
        settings = Settings.from_env()
        queries = load_queries(args.queries)
        with SQLiteStore(settings.db_path) as store:
            observations = store.list_observations(args.limit)
        bundles = analyze_observations(observations, threshold=args.threshold)
        paths = update_ledger(
            RepositoryLedger(args.ledger), observations, bundles, queries, "0.2.0"
        )
        print(json.dumps({"repositories": len(paths), "ledger": args.ledger}))
        return 0
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
