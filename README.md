# AgentTrace

AgentTrace is an open-source defensive research platform for detecting **publicly observable coordination patterns that are consistent with autonomous or semi-autonomous AI agents communicating over Internet services**.

The project is deliberately not an "AI-written text detector." Its primary unit of detection is a **behavioral trajectory** across actors, artifacts, repositories, threads, services, and time.

> Status: operational research alpha. A detection is a hypothesis requiring analyst review, never proof that an account is an AI.

## Why this project exists

Recent agent-security incidents have shown that autonomous agents can discover unexpected ways to persist state, reuse discoveries made by other agents, and coordinate through shared infrastructure. AgentTrace asks a defensive question: **if similar coordination occurs on the public Internet, what observable traces would it leave?**

We focus on signals that are harder to explain with generic AI prose alone:

- rare artifact propagation between identities;
- task delegation, acknowledgement, heartbeat, retry, and checkpoint semantics;
- very fast or highly periodic handoffs;
- graph motifs such as leader/worker fan-out and result aggregation;
- persistence of state across changing identities or execution contexts;
- cross-platform continuation through the same typed coordination marker or
  substantial code fingerprint in canonical or imported JSONL observations.

Live discovery is currently GitHub-centric. Canonical observations can already
represent and correlate other platforms, but live non-GitHub adapters remain
future work.

## MVP architecture

```text
GitHub REST/Search ─┐
GH Archive ─────────┼─> collectors -> namespaced observations -> SQLite
                         |                       |
grep.app (optional) ─┘   |                       +-> typed artifacts
                         |                       +-> relational semantics
                         |                       +-> causal temporal signals
                         |                       +-> composite benign fingerprints
                         v
                   temporal graph
                         |
                         v
                  detector ensemble
                         |
                         v
             priority score + decision tier
                    /              \
             high: pause       non-alert: top-K watchlist
```

The first milestone is GitHub-centric because GitHub gives us precise
timestamps, identities, commits, code artifacts, repository context, and large
public historical datasets. Native pull-request review comments also preserve
reply relationships; ordinary issue comments are conversation members and are
not assigned inferred reply edges.

Canonical observations use platform-scoped `actor_key`, `event_key`,
`parent_key`, resource, and conversation identifiers. Cross-platform or
cross-resource buckets can merge only through the same typed coordination
marker or substantial code artifact. Each artifact links at most ten buckets,
and transitive linked components stop at fifty. Matching usernames never create
that link.

## Data sources

| Source | Purpose | Authentication | Status |
|---|---|---:|---|
| GitHub REST/Search | Live issue/PR/code discovery + thread expansion | Optional token; code search requires auth | Implemented |
| GitHub public Events API | Recent public activity | Optional | Implemented |
| GH Archive | Bounded, streaming historical discovery by UTC hour | None for hourly archives | Implemented |
| grep.app | Fast public-code discovery | None | Experimental adapter |
| JSONL corpus | Reproducible offline evaluation | None | Implemented |

See `docs/search-sources.md` for tradeoffs and scaling strategy.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

agenttrace demo
```

Search GitHub issues and pull requests for coordination markers:

```bash
agenttrace github-thread-search --query '"task_id" OR "heartbeat"' --threads 20 --comments 100
```

With a GitHub token, code search is also available:

```bash
export GITHUB_TOKEN=ghp_xxx
agenttrace github-code-search --query '"task_id" "ack"' --limit 20
```

Search public code through the experimental grep.app adapter:

```bash
agenttrace grep-search --query 'task_id ACK heartbeat' --limit 20
```

Run a bounded GH Archive hour. Candidate-looking events are retained, other
supported events are sampled deterministically, and completed hours are
checkpointed in SQLite:

```bash
agenttrace gharchive-hour --hour 2026-08-16T19 \
  --sample-rate 0.05 \
  --max-observations 10000 \
  --max-download-mb 512
```

Both zero-padded and unpadded input hours are accepted. AgentTrace normalizes
hours `0` through `9` to GH Archive's unpadded object names.

The default event allowlist is `IssuesEvent`, `IssueCommentEvent`,
`PullRequestEvent`, `PushEvent`, and `CreateEvent`. Use `--event-types` to
override it, `--limit` to cap raw events scanned, or `--reprocess` to rerun an
hour whose partition is already marked complete. A completed partition means
the configured scan reached EOF or its explicit raw-event limit. The accepted
observation budget reserves 80% for candidates and 20% for deterministic
background samples; dropped-over-budget counts remain in the ingestion stats.

The archive collector checks event type, event ID, and the cheap candidate
vocabulary on raw bytes before JSON decoding. Only candidate or deterministically
sampled records are decoded. Candidate status is then rechecked against the
normalized event text; for an issue comment this is the comment body, not a copy
of the issue root text.

Analyze an existing JSONL corpus:

```bash
agenttrace analyze-jsonl examples/sample_observations.jsonl
```

Run every seed query across GitHub threads, authenticated GitHub code search,
and grep.app, then deduplicate and rank the combined evidence:

```bash
agenttrace campaign
```

Campaigns retry rate limits, continue when one query or source still fails, and
include those errors in the JSON report. Use `--limit`, `--threads`,
`--comments`, and `--concurrency` to bound API use. The seed query file ships
inside the package; pass `--queries path/to/queries.yaml` to replace it.

Run incremental monitoring with persistent deduplication:

```bash
export AGENTTRACE_DB=/var/lib/agenttrace/agenttrace.db
agenttrace watch --threshold 0.75 --interval 300
```

The monitor rotates a small query batch per cycle and persists a page cursor for
every source/query pair in SQLite. This prevents every cycle from returning to
page one, reduces API bursts, and progressively explores deeper GitHub and
grep.app results. Use `--query-batch-size` to tune the default batch of two.
Page cursors advance only after a source request succeeds, so rate limits and
transient failures do not silently skip result pages.

Each cycle rescans up to 20,000 recent stored observations inside a 24-hour
correlation window, so a new event can connect to earlier repositories or
sources. Tune those bounds with `--history-limit` and `--window-minutes`. Only a
high bundle containing at least one newly discovered event can pause the
monitor, which prevents a previously reviewed historical bundle from stopping
every later cycle.

The monitor stops at the first new reviewable high-tier candidate and prints a
compact evidence summary. When no alert fires, the five highest-scoring
non-alert clusters with nonzero scores are returned as the cycle's watchlist.
The watchlist can contain medium- and low-tier items and always includes each
item's tier. After human review, resolve the alert:

```bash
agenttrace review-alert 1 --status false-positive
```

In continuous mode the worker remains alive while an alert is pending, performs
no source requests, and resumes on its next poll after resolution. `--once`
keeps one-shot behavior and exits with status 2 for a pending alert. Use a
process supervisor or service manager for crash and reboot persistence.

On macOS, `scripts/run-monitor-macos.sh` is a supervisor-friendly entry point.
It reads the existing `gh` CLI credential when no token is already present,
never writes the token to disk, and exposes its bounds through `AGENTTRACE_*`
environment variables. The script deliberately does not install a LaunchAgent;
service installation remains a local administrator decision.

Inspect local growth and event coverage. Opening a missing or older database
will initialize or migrate its schema before reporting health:

```bash
agenttrace db-health
```

## Collaborative repository ledger

Every analyzed repository is written to
`ledger/repos/github/<owner>/<repository>.json`. If that record already exists,
the repository is skipped by default across both `campaign` and `watch`. This
lets contributors share completed coverage through normal Git commits and pull
requests without sharing their local SQLite databases.

Reanalysis is always explicit:

```bash
# Recheck one repository.
agenttrace watch --recheck-repository openfga/api

# Recheck ledger entries at least 30 days old.
agenttrace watch --recheck-stale 30

# Ignore the ledger for this run.
agenttrace watch --recheck-all
```

Export repositories already present in a local database:

```bash
AGENTTRACE_DB=agenttrace.db agenttrace export-ledger
```

By default data is stored in `agenttrace.db`. Override with:

```bash
export AGENTTRACE_DB=/path/to/agenttrace.db
```

## Operational decision policy

AgentTrace assigns `high`, `medium`, or `low` to each cluster. The numeric
`score` is an **operational priority score**, not a calibrated probability that
an account is an AI agent.

A high-tier alert requires all basic eligibility checks: at least two distinct
normalized actor labels, complete public provenance, a benign-automation score below
the suppression ceiling, and a priority score at or above the configured
threshold. It must then have either two independent strong anchor components or
a verified full relational exchange. The verified route is either a native
reply trajectory with distinct delegation, acknowledgement, and result events,
or a typed-reference trajectory of the same shape spanning at least two
conversation, resource, or event contexts. A checkpoint-to-resume path is the
state-transfer equivalent.

The anchor families are typed artifact reuse, relational semantic exchange,
and shared identity markers. Protocol, temporal, and graph signals provide
support but are not anchors. When a signal declares that it depends on another
family's evidence, those families are collapsed into one evidence component.
The component contributes its strongest value plus only a small bounded
correlated-evidence bonus; it cannot masquerade as two independent anchors.

Medium tier starts at `max(0.45, threshold - 0.25)`. It requires either one
strong anchor with another component or collapsed corroboration, or two anchor
components. Everything else is low tier. Bot-like identity alone is not enough
to suppress evidence: the benign detector requires both an automation identity
or app fingerprint and routine workflow behavior, with repeated templates as
additional support.

See [`docs/operational-detection.md`](docs/operational-detection.md) for the
exact routing policy, evaluation metrics, artifact exclusions, and current
scaling limits.

## Repository layout

```text
agenttrace/
├── docs/                       # architecture, threat model, research plan
├── queries/                    # seed discovery queries
├── schemas/                    # canonical observation schema
├── examples/                   # deterministic sample corpus
├── src/agenttrace/
│   ├── collectors/             # GitHub, GH Archive, grep.app, JSONL
│   ├── correlation/            # clustering + graph construction
│   ├── detectors/              # independent signal families
│   ├── storage/                # SQLite evidence store
│   ├── pipeline.py             # analysis orchestration
│   ├── models.py               # typed canonical models
│   └── cli.py                  # command-line interface
└── tests/
```

## Research principles

1. **Trajectory over message.** One message is weak evidence. Sequences are stronger.
2. **Evidence over attribution.** Preserve public provenance and uncertainty.
3. **Multiple independent signals.** No single regex or LLM judgement decides an alert.
4. **Passive by default.** Observe public data; do not interact with suspected agents.
5. **No exploitation.** Never execute discovered payloads or probe targets.
6. **Reproducibility.** Every detector should be testable against a versioned corpus.
7. **Open collaboration.** Detection ideas should be proposed as documented signal families with false-positive analysis.

## Contributing

Contributions are welcome, especially:

- new public-data collectors;
- graph/temporal detectors;
- benign-automation fingerprints;
- labeled negative corpora;
- cross-platform correlation research;
- visualization and analyst tooling;
- reproducible evaluation datasets.

Read `CONTRIBUTING.md`, `SECURITY.md`, and `docs/research-hypotheses.md` before opening a PR.

## License

Apache License 2.0. See `LICENSE`.
