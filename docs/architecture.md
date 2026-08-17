# Architecture

## Objective

Detect clusters of **public Internet activity** that exhibit coordination patterns consistent with autonomous or semi-autonomous agents. The system produces evidence-backed hypotheses, not identity attribution.

## System planes

### 1. Collection plane

Collectors implement one interface and emit immutable canonical `Observation` objects.

Initial adapters:

- GitHub Search API for issues/PRs;
- GitHub Code Search API when authenticated;
- GitHub public Events API;
- GH Archive hourly event files;
- grep.app public code search as an experimental discovery source;
- JSONL replay for reproducible evaluation.

Future adapters should be passive/public by default: Stack Exchange dumps/APIs, public mailing lists, public package registries, RSS/Atom forums, Common Crawl-derived datasets, and other public corpora.

### 2. Normalization plane

Every source becomes:

```text
source
source_event_id
observed_at
event_time
actor
event_type
repository
text
thread_id
reply_to
artifact_urls
code_blocks
content_sha256
metadata
provenance
```

`source + source_event_id` is the storage idempotency key.

### 3. Feature plane

Independent signal families are intentionally isolated.

**Protocol:** task IDs, ACK/NACK, heartbeats, retries, sequence numbers, checkpoints, queues, worker/coordinator terminology, integrity markers.

**Temporal:** cross-actor handoff latency, periodicity, burstiness, synchronized activity, 24x7 persistence.

**Artifact:** exact propagation of rare URLs, code fingerprints, long tokens, hashes, keys, nonces, unusual error strings.

**Identity:** explicit shared public keys, fingerprints, worker IDs, or declared aliases. This links pseudonymous clusters; it does not deanonymize people.

**Graph:** reply relationships, shared artifacts, fan-out, reciprocity, strongly connected actor groups, delegation/result-aggregation motifs.

**Semantic:** explicit delegation, state transfer, results, sandbox/tooling language. This is supporting evidence, not proof.

**Benign:** known bots and automation patterns. This becomes a negative score.

### 4. Correlation plane

MVP clustering is intentionally simple and auditable: source + repository + thread + time window. The graph is heterogeneous:

```text
actor -> event -> repository
              -> artifact

event -> event       (reply)
actor -> actor        (response / shared artifact)
```

The next phase should add cross-platform entity resolution using unique public artifacts and tokens.

### 5. Scoring plane

Current weights:

```text
protocol   0.15
temporal   0.20
artifact   0.25
graph      0.20
semantic   0.10
identity   0.10

benign penalty: -0.40 * benign_score
```

An alert requires at least three positive signal families and one high-value family.

## Scale-out path

### Alpha

- SQLite
- batch processing
- NetworkX
- direct HTTP adapters

### Beta

- PostgreSQL + pgvector
- object storage for immutable raw evidence
- scheduled ingestion
- feature materialization

### Internet-scale

- Kafka/Redpanda ingestion
- ClickHouse event analytics
- OpenSearch text/artifact index
- Neo4j/Memgraph interactive graph exploration
- S3-compatible evidence lake
- Spark/BigQuery for historical replay
- calibrated statistical/graph models

## Why not start with an LLM classifier?

A semantic model is useful for interpreting coordination semantics, but a language-only detector will overfit to writing style and be easy to evade. AgentTrace therefore treats semantic inference as one weak family inside a broader evidence graph.
