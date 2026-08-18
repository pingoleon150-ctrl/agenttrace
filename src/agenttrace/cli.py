from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agenttrace import __version__
from agenttrace.calibration import CalibrationProfile
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
from agenttrace.corpus import evaluate_labeled_corpus
from agenttrace.ledger import RepositoryLedger, update_ledger
from agenttrace.models import Observation, Provenance
from agenttrace.monitor import take_watch_query_batch, watch_cycle
from agenttrace.notifier import notify_email_alerts
from agenttrace.pipeline import analyze_cluster, analyze_observations, collect_to_store
from agenttrace.reviewer import reviewer_from_openclaw, write_findings_report
from agenttrace.storage.parquet import write_observation_parquet
from agenttrace.storage.sqlite import SQLiteStore

DEFAULT_QUERIES_PATH = Path(__file__).with_name("data") / "seed_queries.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agenttrace", description="Detect public agent-coordination patterns"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
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
    p.add_argument("--limit", type=int, default=None, help="Optional raw-event scan cap")
    p.add_argument("--sample-rate", type=float, default=0.05)
    p.add_argument(
        "--event-types",
        default="IssuesEvent,IssueCommentEvent,PullRequestEvent,PushEvent,CreateEvent",
    )
    p.add_argument("--max-observations", type=int, default=10000)
    p.add_argument("--max-download-mb", type=float, default=512.0)
    p.add_argument("--reprocess", action="store_true")
    p.add_argument(
        "--repository",
        action="append",
        default=[],
        help="Target one repository (owner/name); repeat for a directed replay",
    )
    p.add_argument("--threshold", type=float, default=0.60)
    p.add_argument(
        "--parquet",
        help="Optional DuckDB/Parquet path for prefiltered canonical archive events",
    )

    p = sub.add_parser("analyze-jsonl", help="Analyze a canonical Observation JSONL file")
    p.add_argument("path")
    p.add_argument("--threshold", type=float, default=0.60)
    p.add_argument(
        "--calibration",
        help="Optional JSON likelihood-ratio profile; probabilities require a field-valid prior",
    )

    p = sub.add_parser(
        "evaluate-corpus", help="Evaluate detectors against labeled scenario ground truth"
    )
    p.add_argument("observations", help="Canonical Observation JSONL")
    p.add_argument("labels", help="Scenario labels JSON")
    p.add_argument("--threshold", type=float, default=0.60)

    p = sub.add_parser(
        "export-reviewable", help="Print reviewable evidence bundles from current DB"
    )
    p.add_argument("--limit", type=int, default=10000)
    p.add_argument("--threshold", type=float, default=0.60)

    p = sub.add_parser("campaign", help="Run a multi-query, multi-source discovery campaign")
    p.add_argument("--queries", default=str(DEFAULT_QUERIES_PATH))
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
    p.add_argument("--calibration", help="Optional JSON likelihood-ratio profile")
    _add_ledger_arguments(p)

    p = sub.add_parser(
        "watch", help="Continuously discover new evidence and pause on a reviewable high-tier candidate"
    )
    p.add_argument("--queries", default=str(DEFAULT_QUERIES_PATH))
    p.add_argument("--sources", default="github-thread,github-code,grep")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--threads", type=int, default=5)
    p.add_argument("--comments", type=int, default=50)
    p.add_argument("--threshold", type=float, default=0.75)
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--retries", type=int, default=2)
    p.add_argument("--interval", type=int, default=300)
    p.add_argument(
        "--history-limit",
        type=int,
        default=20000,
        help="Recent observations rescored each cycle for longitudinal/cross-resource links",
    )
    p.add_argument(
        "--window-minutes",
        type=int,
        default=1440,
        help="Correlation window for monitor history (default: 24 hours)",
    )
    p.add_argument(
        "--query-batch-size",
        type=int,
        default=2,
        help="Queries rotated per cycle; cursors persist in SQLite",
    )
    p.add_argument("--once", action="store_true")
    p.add_argument("--calibration", help="Optional JSON likelihood-ratio profile")
    p.add_argument(
        "--auto-review",
        action="store_true",
        help="Classify high-tier findings with an OpenClaw-configured LLM and continue",
    )
    p.add_argument(
        "--openclaw-config",
        default="~/.openclaw/openclaw.json",
        help="Private OpenClaw configuration read at runtime; never copied into reports",
    )
    p.add_argument("--review-provider", default="gateway")
    p.add_argument("--review-model", help="Override the provider's first configured model")
    p.add_argument(
        "--findings-report",
        default="reports/findings.md",
        help="Single regenerated public Markdown findings report",
    )
    _add_ledger_arguments(p)

    p = sub.add_parser("review-alert", help="Resolve a paused monitor alert")
    p.add_argument("alert_id", type=int)
    p.add_argument("--status", choices=["reviewed", "false-positive", "escalated"], required=True)

    sub.add_parser("db-health", help="Report local database size, event range, and row counts")

    p = sub.add_parser(
        "notify-email", help="Send unnotified monitor alerts through macOS Mail"
    )
    p.add_argument("--db", required=True, help="AgentTrace monitor SQLite database")
    p.add_argument("--recipient", required=True)
    p.add_argument("--test", action="store_true", help="Send a delivery test without changing state")

    p = sub.add_parser(
        "export-ledger", help="Export analyzed repositories from SQLite to the shared ledger"
    )
    p.add_argument("--queries", default=str(DEFAULT_QUERIES_PATH))
    p.add_argument("--ledger", default="ledger/repos")
    p.add_argument("--limit", type=int, default=100000)
    p.add_argument("--threshold", type=float, default=0.75)

    p = sub.add_parser("export-findings", help="Regenerate the public findings Markdown report")
    p.add_argument("--report", default="reports/findings.md")

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


async def _run_collector(
    collector, threshold: float, calibration: CalibrationProfile | None = None
) -> int:
    settings = Settings.from_env()
    with SQLiteStore(settings.db_path) as store:
        observations = await collect_to_store(collector, store)
        bundles = analyze_observations(
            observations, threshold=threshold, calibration=calibration
        )
        _save_bounded_bundles(store, bundles)
        _print_summary(observations, bundles)
    return 0


async def _run_gharchive(args) -> int:
    settings = Settings.from_env()
    event_types = {value.strip() for value in args.event_types.split(",") if value.strip()}
    if not event_types:
        raise ValueError("--event-types must contain at least one event type")
    collector = GHArchiveHourCollector(
        args.hour,
        args.limit,
        settings,
        sample_rate=args.sample_rate,
        event_types=event_types,
        max_observations=args.max_observations,
        max_download_bytes=int(args.max_download_mb * 1024 * 1024),
        repositories=set(args.repository),
    )
    with SQLiteStore(settings.db_path) as store:
        partition = store.ingestion_partition("gharchive", collector.hour)
        if partition and partition["status"] == "complete" and not args.reprocess:
            print(
                json.dumps(
                    {
                        "state": "skipped",
                        "reason": "partition_complete",
                        "partition": collector.hour,
                        "stats": partition["stats"],
                    },
                    indent=2,
                )
            )
            return 0
        store.start_ingestion_partition("gharchive", collector.hour, datetime.now(UTC).isoformat())
        try:
            observations = await collect_to_store(collector, store)
            bundles = analyze_observations(observations, threshold=args.threshold)
            _save_bounded_bundles(store, bundles)
        except Exception as exc:
            store.finish_ingestion_partition(
                "gharchive",
                collector.hour,
                "failed",
                datetime.now(UTC).isoformat(),
                collector.stats,
                f"{type(exc).__name__}: {exc}",
            )
            raise
        store.finish_ingestion_partition(
            "gharchive",
            collector.hour,
            "complete",
            datetime.now(UTC).isoformat(),
            collector.stats,
        )
        if args.parquet:
            write_observation_parquet(args.parquet, observations)
        _print_summary(observations, bundles, ingestion=collector.stats)
    return 0


def _save_bounded_bundles(store: SQLiteStore, bundles, limit: int = 100) -> None:
    ranked = sorted(bundles, key=lambda bundle: bundle.score.score, reverse=True)
    selected = {bundle.cluster_id: bundle for bundle in ranked[:limit]}
    selected.update({bundle.cluster_id: bundle for bundle in bundles if bundle.score.reviewable})
    for bundle in selected.values():
        store.save_bundle(bundle)


def _print_summary(observations, bundles, ingestion: dict | None = None) -> None:
    reviewable = [b for b in bundles if b.score.reviewable]
    result = {
        "observations": len(observations),
        "clusters": len(bundles),
        "reviewable_clusters": len(reviewable),
        "confidence": {
            level: sum(1 for bundle in bundles if bundle.score.confidence == level)
            for level in ("high", "medium", "low")
        },
        "top_clusters": [
            {
                "cluster_id": b.cluster_id,
                "score": b.score.score,
                "priority_score": b.score.score,
                "reviewable": b.score.reviewable,
                "actors": b.actors,
                "reasons": b.score.reasons,
                "provenance": [o.provenance.url for o in b.observations[:10]],
            }
            for b in sorted(bundles, key=lambda x: x.score.score, reverse=True)[:20]
        ],
    }
    if ingestion is not None:
        result["ingestion"] = ingestion
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
            text=f"Delegate task_id=probe-9917 to worker. nonce={common_artifact}",
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
            text=f"ACK task_id=probe-9917 nonce={common_artifact}",
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
            text="Task completed task_id=probe-9917; result: success",
            repository="demo/swarm",
            thread_id="42",
            reply_to="1",
            provenance=Provenance(url="https://example.invalid/4"),
        ),
    ]
    bundle = analyze_cluster("demo:swarm:42", observations, threshold=0.75)
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
    calibration = CalibrationProfile.load(args.calibration) if args.calibration else None
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
            calibration=calibration,
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
    calibration = CalibrationProfile.load(args.calibration) if args.calibration else None
    reviewer = (
        reviewer_from_openclaw(args.openclaw_config, args.review_provider, args.review_model)
        if args.auto_review
        else None
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
            queries = take_watch_query_batch(store, all_queries, args.query_batch_size)
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
                history_limit=args.history_limit,
                window_minutes=args.window_minutes,
                calibration=calibration,
                reviewer=reviewer,
                report_path=args.findings_report if reviewer else None,
            )
        print(json.dumps(result.as_dict(), indent=2), flush=True)
        if args.once:
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
        return asyncio.run(_run_gharchive(args))
    if args.command == "analyze-jsonl":
        calibration = CalibrationProfile.load(args.calibration) if args.calibration else None
        return asyncio.run(
            _run_collector(JsonlCollector(args.path), args.threshold, calibration=calibration)
        )
    if args.command == "evaluate-corpus":
        print(
            json.dumps(
                evaluate_labeled_corpus(args.observations, args.labels, args.threshold), indent=2
            )
        )
        return 0
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
    if args.command == "export-findings":
        settings = Settings.from_env()
        with SQLiteStore(settings.db_path) as store:
            findings = store.monitor_findings()
        write_findings_report(args.report, findings)
        print(json.dumps({"report": args.report, "findings": len(findings)}))
        return 0
    if args.command == "db-health":
        settings = Settings.from_env()
        with SQLiteStore(settings.db_path) as store:
            print(json.dumps(store.health(), indent=2))
        return 0
    if args.command == "notify-email":
        sent = notify_email_alerts(args.db, args.recipient, test=args.test)
        print(json.dumps({"sent": sent, "test": args.test}))
        return 0
    if args.command == "export-ledger":
        settings = Settings.from_env()
        queries = load_queries(args.queries)
        with SQLiteStore(settings.db_path) as store:
            observations = store.list_observations(args.limit)
        bundles = analyze_observations(observations, threshold=args.threshold)
        paths = update_ledger(
            RepositoryLedger(args.ledger), observations, bundles, queries, __version__
        )
        print(json.dumps({"repositories": len(paths), "ledger": args.ledger}))
        return 0
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
