from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from agenttrace.collectors.gharchive import GHArchiveHourCollector
from agenttrace.collectors.github import GitHubCodeSearchCollector, GitHubIssueSearchCollector, GitHubPublicEventsCollector, GitHubThreadSearchCollector
from agenttrace.collectors.grepapp import GrepAppCollector
from agenttrace.collectors.jsonl import JsonlCollector
from agenttrace.config import Settings
from agenttrace.models import Observation, Provenance
from agenttrace.pipeline import analyze_cluster, analyze_observations, collect_to_store
from agenttrace.storage.sqlite import SQLiteStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agenttrace", description="Detect public agent-coordination patterns")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("demo", help="Run a deterministic synthetic coordination demo")

    p = sub.add_parser("github-search", help="Search public GitHub issues and pull requests")
    p.add_argument("--query", required=True)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--threshold", type=float, default=0.60)


    p = sub.add_parser("github-thread-search", help="Search GitHub and expand candidate issue/PR conversations")
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

    p = sub.add_parser("grep-search", help="Search public code using the experimental grep.app adapter")
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

    p = sub.add_parser("export-reviewable", help="Print reviewable evidence bundles from current DB")
    p.add_argument("--limit", type=int, default=10000)
    p.add_argument("--threshold", type=float, default=0.60)

    return parser


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
    t0 = datetime.now(timezone.utc)
    common_artifact = "artifact-7f9c2a11-checkpoint-8891"
    observations = [
        Observation(source="demo", source_event_id="1", observed_at=t0, event_time=t0,
            actor="coord", event_type="post", text=f"TASK-ID: probe-991 delegate worker. nonce={common_artifact}",
            repository="demo/swarm", thread_id="42", code_blocks=[common_artifact],
            provenance=Provenance(url="https://example.invalid/1")),
        Observation(source="demo", source_event_id="2", observed_at=t0, event_time=t0+timedelta(seconds=8),
            actor="worker-a", event_type="reply", text=f"ACK task probe-991 seq=2 {common_artifact}",
            repository="demo/swarm", thread_id="42", reply_to="1", code_blocks=[common_artifact],
            provenance=Provenance(url="https://example.invalid/2")),
        Observation(source="demo", source_event_id="3", observed_at=t0, event_time=t0+timedelta(seconds=17),
            actor="coord", event_type="reply", text="heartbeat worker alive retry_count=1 checkpoint",
            repository="demo/swarm", thread_id="42", reply_to="2",
            provenance=Provenance(url="https://example.invalid/3")),
        Observation(source="demo", source_event_id="4", observed_at=t0, event_time=t0+timedelta(seconds=25),
            actor="worker-a", event_type="reply", text="ACK result completed report back",
            repository="demo/swarm", thread_id="42", reply_to="3",
            provenance=Provenance(url="https://example.invalid/4")),
    ]
    bundle = analyze_cluster("demo:swarm:42", observations, threshold=0.50)
    print(bundle.model_dump_json(indent=2))
    return 0


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "demo":
        return _demo()
    if args.command == "github-search":
        return asyncio.run(_run_collector(GitHubIssueSearchCollector(args.query, args.limit), args.threshold))
    if args.command == "github-thread-search":
        return asyncio.run(_run_collector(GitHubThreadSearchCollector(args.query, args.threads, args.comments), args.threshold))
    if args.command == "github-code-search":
        return asyncio.run(_run_collector(GitHubCodeSearchCollector(args.query, args.limit), args.threshold))
    if args.command == "github-events":
        return asyncio.run(_run_collector(GitHubPublicEventsCollector(args.pages), args.threshold))
    if args.command == "grep-search":
        return asyncio.run(_run_collector(GrepAppCollector(args.query, args.limit), args.threshold))
    if args.command == "gharchive-hour":
        return asyncio.run(_run_collector(GHArchiveHourCollector(args.hour, args.limit), args.threshold))
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
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
