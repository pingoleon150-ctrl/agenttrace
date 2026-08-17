# AgentTrace

AgentTrace is an open-source defensive research platform for detecting **publicly observable coordination patterns that are consistent with autonomous or semi-autonomous AI agents communicating over Internet services**.

The project is deliberately not an "AI-written text detector." Its primary unit of detection is a **behavioral trajectory** across actors, artifacts, repositories, threads, services, and time.

> Status: early research alpha. A detection is a hypothesis requiring analyst review, never proof that an account is an AI.

## Why this project exists

Recent agent-security incidents have shown that autonomous agents can discover unexpected ways to persist state, reuse discoveries made by other agents, and coordinate through shared infrastructure. AgentTrace asks a defensive question: **if similar coordination occurs on the public Internet, what observable traces would it leave?**

We focus on signals that are harder to explain with generic AI prose alone:

- rare artifact propagation between identities;
- task delegation, acknowledgement, heartbeat, retry, and checkpoint semantics;
- very fast or highly periodic handoffs;
- graph motifs such as leader/worker fan-out and result aggregation;
- persistence of state across changing identities or execution contexts;
- cross-platform continuation using the same unique tokens, hashes, URLs, keys, or snippets.

## MVP architecture

```text
GitHub REST/Search ─┐
GH Archive ─────────┼─> collectors -> canonical observations -> SQLite
                         |                  |
grep.app (optional) ─┘   |                  +-> artifact extraction
                         |                  +-> protocol signals
                         |                  +-> temporal signals
                         |                  +-> benign-bot suppression
                         v
                   temporal graph
                         |
                         v
                  detector ensemble
                         |
                         v
                 evidence bundle
```

The first milestone is GitHub-centric because GitHub gives us precise timestamps, identities, reply relationships, commits, code artifacts, repository context, and large public historical datasets.

## Data sources

| Source | Purpose | Authentication | Status |
|---|---|---:|---|
| GitHub REST/Search | Live issue/PR/code discovery + thread expansion | Optional token; code search requires auth | Implemented |
| GitHub public Events API | Recent public activity | Optional | Implemented |
| GH Archive | Historical / large-scale event replay | None for hourly archives | Implemented |
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

Replay an hour from GH Archive:

```bash
agenttrace gharchive-hour --hour 2026-08-16T19 --limit 5000
```

Analyze an existing JSONL corpus:

```bash
agenttrace analyze-jsonl examples/sample_observations.jsonl
```

By default data is stored in `agenttrace.db`. Override with:

```bash
export AGENTTRACE_DB=/path/to/agenttrace.db
```

## What constitutes a candidate detection?

A cluster becomes reviewable only when multiple independent signal families fire. The default scorer requires:

- at least three independent signal families;
- at least one high-value signal family (temporal, artifact, graph, or identity);
- at least two distinct public actors;
- a score above the configured threshold;
- preserved provenance for analyst verification.

Known automation such as Dependabot, Renovate, GitHub Actions bots, release bots, and common CI identities is explicitly down-weighted.

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
