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
- opaque high-entropy exchanges and shared credential-like markers with
  event-context identifier suppression;
- continuous multi-actor coverage and cross-repository objective persistence;
- commit-message uniformity, exact machine-like push timing, and generated
  author-domain reuse (email local parts are not retained);
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

For directed replay, repeat `--repository owner/name`. Nonmatching events are
discarded from raw bytes before JSON decoding, making it practical to revisit
only repositories promoted by an earlier cheap discovery pass.

Install the archive extra and add `--parquet path/to/hour.parquet` to retain
the bounded, prefiltered canonical events in a Zstandard-compressed columnar
file. SQLite remains the small operational store for checkpoints, deduplication,
alerts, and evidence bundles; it is no longer required to serve as the raw
historical event warehouse.

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

Evaluate the bundled labeled regression corpus:

```bash
agenttrace evaluate-corpus \
  corpus/synthetic-v2/observations.jsonl \
  corpus/synthetic-v2/labels.json
```

The report uses labeled scenarios, not individual correlated events, and emits
a confusion matrix plus smoothed signal-presence likelihood ratios. These are
in-sample diagnostics. They must not be interpreted as field probabilities.
An optional external calibration profile can be applied to JSONL analysis with
`--calibration profile.json`; its posterior is valid only when its corpus and
deployment prior are valid for the target population.

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

By default, the monitor stops at the first new reviewable high-tier candidate and prints a
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

For continuous LLM-assisted triage, enable automatic review. Every new high-tier
candidate in the cycle is sanitized, classified through an OpenAI-compatible
provider already configured in the private OpenClaw configuration, recorded in
SQLite, and added to one regenerated public report. The monitor continues even
when classification fails; failed items are labeled `classification-error` for
later retry instead of blocking collection.

```bash
export AGENTTRACE_DB=/var/lib/agenttrace/agenttrace.db
agenttrace watch \
  --auto-review \
  --openclaw-config ~/.openclaw/openclaw.json \
  --review-provider gateway \
  --findings-report reports/findings.md \
  --findings-html reports/site/index.html
```

The API key is read only at runtime. It is never stored in SQLite, the shared
ledger, monitor output, or `reports/findings.md`. Before transmission, public
observation text is bounded and common credential patterns are redacted. The
classifier must distinguish ordinary automation, human collaboration,
AI-assisted work, semi-autonomous coordination, and evidence of full autonomy;
the detector score remains a review priority rather than a probability.

Regenerate the report from the local review ledger without making an LLM call:

```bash
AGENTTRACE_DB=agenttrace-monitor.db agenttrace export-findings \
  --report reports/findings.md \
  --html reports/site/index.html
```

The monitor regenerates both files atomically after each classified finding. The HTML dashboard
can be published on a trusted home LAN without exposing the database, logs, or OpenClaw config:

```bash
AGENTTRACE_SITE_DIRECTORY=reports/site \
AGENTTRACE_REPORT_HOST=0.0.0.0 \
AGENTTRACE_REPORT_PORT=8765 \
scripts/run-report-server-macos.sh
```

Open `http://<laptop-lan-ip>:8765/` from another device on the same network. The read-only page
auto-refreshes every five minutes, escapes public evidence, and uses a restrictive Content
Security Policy. This does not create Internet access or router port forwarding.

On macOS, a separate private LaunchAgent can poll the monitor database and send
each new alert exactly once through the configured Mail.app account:

```bash
agenttrace notify-email \
  --db /path/to/agenttrace-monitor.db \
  --recipient alerts@example.com
```

The recipient belongs in the local LaunchAgent rather than the repository. A
one-way hash and the last delivered alert ID are stored in SQLite to suppress
duplicates; the address itself is not persisted in the database.

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

A high-tier alert requires complete public provenance, a benign-automation
score below the suppression ceiling, and a priority score at or above the
configured threshold. It normally requires at least two distinct actors, but a
longitudinal cross-repository persistence signal may make a single-actor case
reviewable. Routing then requires two independent strong anchor components, a
verified full relational exchange, or one narrowly defined exceptional signal
such as a repeated high-entropy cross-actor exchange or a shared credential
across identities and repositories. The verified route is either a native
reply trajectory with distinct delegation, acknowledgement, and result events,
or a typed-reference trajectory of the same shape spanning at least two
conversation, resource, or event contexts. A checkpoint-to-resume path is the
state-transfer equivalent.

Three independent strong anchor components produce `decision=confirmed`;
review routes with fewer components produce `decision=review`. This is an
operational evidence state, not attribution proof.

The anchor families are typed artifact reuse, relational semantic exchange,
shared identity markers, longitudinal behavior, and commit metadata. Protocol,
temporal, and graph signals provide support but are not anchors. When a signal declares that it depends on another
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
