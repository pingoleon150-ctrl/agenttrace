# Architecture

## Objective

Detect clusters of public Internet activity that exhibit coordination patterns
consistent with autonomous or semi-autonomous agents. The system produces
evidence-backed hypotheses for analyst review; it does not attribute an
identity or prove that an actor is an AI.

## System planes

### 1. Collection plane

Collectors implement one asynchronous interface and emit canonical
`Observation` objects.

Current adapters are:

- GitHub Search API for issues and pull requests;
- GitHub Code Search API when authenticated;
- GitHub public Events API;
- GH Archive hourly event files;
- grep.app public code search as an experimental discovery source;
- JSONL replay for reproducible evaluation.

Collectors are passive and operate only on public data. Future adapters should
preserve that boundary and emit the same canonical model rather than adding
source-specific logic to the detector pipeline.

GH Archive is a bounded discovery collector, not an unbounded event warehouse.
It incrementally decompresses the HTTP stream, restricts processing to selected
event types, retains cheap coordination-keyword candidates, and takes a stable
hash sample of the remaining relevant events. Event type, event ID, candidate
vocabulary, and sampling are checked on raw bytes so rejected records are never
JSON-decoded. Retained records are normalized and candidate status is rechecked
against the actual event text. In particular, an issue comment contains only
the comment body; candidate text from the issue root is not copied into every
comment. Defaults cap accepted observations at 10,000, compressed input at
512 MiB, an individual event at 2 MiB, and retained text at 20,000 characters.
The observation budget reserves 80% for candidates and 20% for background;
collection continues scanning after either accepted quota fills. Retained code
blocks and URLs are separately bounded. Accepted observations are written to
SQLite in batches of 500.

### 2. Normalization and namespace plane

Every source becomes:

```text
source
source_event_id
event_key
observed_at
event_time
actor
platform
actor_key
event_type
text
repository
resource_key
thread_id
conversation_key
reply_to
parent_key
artifact_urls
code_blocks
content_sha256
metadata
provenance
```

`source + source_event_id` is the storage idempotency key. Entity and
conversation keys are platform-namespaced:

```text
github:actor:alice
github:event:github-thread-search:comment:123
github:repository:owner/project
github:repository:owner/project:thread:42
```

Clustering prefers `conversation_key`, then `resource_key`, then `event_key`.
`parent_key` is the namespaced target of a reply and prevents the same raw event
ID from connecting unrelated sources. These keys prevent an actor, event,
repository, or thread identifier from one service from colliding accidentally
with the same raw string on another service. Namespacing is infrastructure for
cross-platform correlation; it never asserts that similarly named actors on
different platforms are the same entity.

### 3. Feature plane

Signal families are isolated so each can be evaluated and ablated separately.

**Protocol.** Explicit task identifiers, acknowledgements, heartbeats, retries,
sequence numbers, checkpoints, queues, worker/coordinator terminology, and
integrity markers. Protocol is supporting evidence, not an anchor family.

**Relational semantic.** A strong semantic signal is a cross-actor exchange,
not a coordination-looking word in one message. The implemented paths are
delegation to result and checkpoint to resume. Events must be linked by an
explicit reply or a shared typed task/state reference. A linked acknowledgement
strengthens the path only when it is a distinct event from both delegation and
result. Markdown quotations, fenced code, HTML details/blockquote summaries,
negated instructions, and isolated generic build, result, or deployment
language do not form a strong semantic exchange.

**Artifact.** The extractor admits typed evidence only:

- values attached to coordination keys such as `task_id`, `run_id`, `nonce`,
  `checkpoint`, or `resume_token`;
- sufficiently substantial canonical code blocks;
- normalized external URLs.

It does not treat arbitrary long strings, bare commit SHAs, generic hashes,
UUIDs, issue numbers, or provenance URLs as artifacts. Common GitHub URLs,
tracking parameters, placeholders, low-diversity values, all-numeric values,
short code fragments, and Markdown quotations are excluded or normalized.
Hash- or UUID-shaped values are considered only when attached to an explicit
coordination key, and receive less strength than a distinctive typed marker.

**Temporal.** Fast actor changes count only when adjacent events have a causal
link: an explicit reply or a shared typed artifact. Raw alternation between
accounts is insufficient. Periodicity remains supporting evidence and is not an
anchor family.

**Identity.** Explicit shared public keys, fingerprint values, or key IDs can
link pseudonymous activity only when the marker crosses both actors and
contexts. Quoted copies and same-thread repetition do not activate the family.
This signal does not deanonymize people.

**Graph.** Native reply relationships create event-parent and cross-actor
edges. Typed artifacts may be represented as event-to-artifact context, but do
not create actor-to-actor edges or graph-family evidence. Reciprocity, fan-out,
and strongly connected actor groups are supporting topological evidence. Two
events merely appearing in the same repository do not create an actor-to-actor
coordination edge.

**Benign automation.** Suppression uses a composite fingerprint. It requires
both a bot/app-like identity and routine workflow behavior such as dependency
updates, CI summaries, generated releases, or standard deployment events.
Repeated normalized templates add support. A username ending in `[bot]`, or a
message containing ordinary words such as "build" and "deploy," is not enough
on its own.

### 4. Correlation plane

The current correlator groups observations by their namespaced conversation or
resource and then divides them into deterministic time windows. Within a
cluster the graph is heterogeneous:

```text
actor -> event -> resource
              -> typed artifact

event -> event       (reply)
actor -> actor        (cross-actor response)
```

Before time-window clustering, the correlator may merge between two and ten
otherwise separate buckets when the same typed coordination marker or
substantial code artifact appears across at least two namespaced actors and the
matches span platforms or resources. External URLs do not perform this merge.
Username equality never links platform buckets, and similar names or prose are
not evidence of cross-platform identity.

Transitive artifact unions are capped at fifty buckets. The semantic matcher
indexes typed references and native reply ancestry, caps high-frequency
references and emitted paths, and avoids an all-pairs comparison over a busy
cluster.

### 5. Priority scoring plane

The serialized `score` is an operational priority score. It is **not a
calibrated probability**, posterior belief, or percentage likelihood that an
actor is autonomous.

For each signal family, only the strongest signal is retained. Raw family
signals below 0.35 are excluded. Remaining family strengths are multiplied by
reliability factors:

```text
protocol   0.90
temporal   0.65
artifact   0.95
graph      0.70
semantic   1.00
identity   1.00
```

Signals can declare dependencies on other families when they reuse the same
underlying evidence. All explicitly dependent families are collapsed into one
evidence component, whose strength is the maximum effective family strength in
that component. This prevents, for example, a semantic exchange linked only by
a typed artifact from counting as an independent semantic anchor plus an
independent artifact anchor.

The three strongest evidence components contribute 0.52, 0.31, and 0.17 of
their strength. Diversity adds 0.03 when at least two components exist and
another 0.03 when at least three exist. Collapsed families add only 0.03 each,
capped at 0.06 total, as correlated corroboration. A verified relational
exchange can raise the pre-penalty positive score to a floor of 0.80. The
composite benign score then applies the multiplicative factor
`1 - 0.65 * benign_score`, and the result is clamped to the interval from zero
to one. This ranking formula is intentionally interpretable, but its output
must not be described as calibrated confidence.

### 6. Decision plane

The decision tier is separate from the numeric priority score.

Basic eligibility requires:

- two or more distinct normalized actor labels (the same raw handle on two
  platforms does not satisfy this gate by itself);
- complete public provenance;
- a benign score below 0.80.

The anchor families are artifact, relational semantic, and identity. Protocol,
temporal, and graph are supporting families. An anchor component is strong when
it contains an anchor family whose reliability-adjusted strength is at least
0.68.

**High.** The cluster is eligible, meets the configured score threshold, and
has either two independent strong anchor components or a verified full
relational exchange. A verified native route requires distinct delegation,
acknowledgement, and result events connected through real reply ancestry. A
shared-reference route requires the equivalent trajectory across at least two
contexts plus a fired typed artifact. Checkpoint-to-resume is the state-transfer
equivalent. A high-tier cluster is reviewable and pauses source collection.

**Medium.** The cluster is eligible but not high, meets
`max(0.45, threshold - 0.25)`, and has either one strong anchor component plus
another independent component or collapsed corroboration, or at least two
anchor components.

**Low.** Every other cluster.

When no high alert exists, the monitor returns the five highest-scoring
non-alert clusters with scores above zero. This watchlist can contain both
medium and low tiers and always exposes the tier. Repeated observations inside
one family cannot satisfy the independent-anchor requirement, and explicitly
dependent families remain one component.

### 7. Storage and checkpoint plane

SQLite uses WAL mode, batched observation upserts, and idempotent source/event
keys. Evidence-bundle persistence is bounded for bulk single-source runs: the
top 100 bundles plus every reviewable bundle are retained.

Discovery cursor state accepts opaque JSON values, allowing a future adapter to
store a page number, `after` token, timestamp, or offset. Current GitHub and
grep.app adapters use integer-page compatibility wrappers around that generic
state.

The monitor rescans a bounded recent history on every cycle: 20,000
observations and a 1,440-minute correlation window by default. This permits a
new event to join an older cross-resource candidate without turning SQLite into
an unbounded analytical warehouse. A high bundle pauses the monitor only when
it contains an event discovered in the current cycle, so resolved historical
evidence cannot repeatedly recreate the same pause.

Continuous `watch` remains alive while an alert is pending and polls only local
alert state. Resolving the alert lets the same process resume on its next
interval; `--once` retains the exit-on-alert behavior.

GH Archive records an hour-level ingestion partition with `running`, `complete`,
or `failed` status and summary counters. A completed partition is skipped unless
`--reprocess` is supplied. This checkpoint is deliberately modest: it prevents
accidental replay of a completed bounded job, but it is not a byte-offset or
line-level resume point. A failed process starts that hour again, relying on
idempotent upserts and deterministic sampling. Likewise, `complete` means the
stream reached EOF or the explicit raw scan limit, not that every matching event
fit inside its accepted candidate/background quota.

## Scale-out path

### Current operational alpha

- one host and one SQLite writer;
- bounded query rotation and source-specific page cursors;
- bounded GH Archive streaming and deterministic sampling;
- NetworkX analysis over accepted observations;
- a shared Git ledger for repository-level deduplication;
- human review at the high-tier pause gate.

### Multi-worker beta

- PostgreSQL for concurrent state and leases;
- object storage for immutable compressed source partitions;
- a durable enrichment queue for candidate threads and repositories;
- materialized features and normalized bundle/observation relations;
- per-source rate-limit budgets and health metrics;
- versioned labeled corpora and empirical tier calibration.

### Internet scale

- Kafka or Redpanda ingestion;
- ClickHouse event analytics;
- OpenSearch text and artifact retrieval;
- a graph store for interactive investigation;
- S3-compatible evidence storage;
- distributed historical replay;
- calibrated statistical or learned ranking models evaluated on held-out time
  and repository splits.

The limits of the current implementation are documented in
[`operational-detection.md`](operational-detection.md).

## Why not start with a language-only classifier?

A semantic model can help interpret coordination exchanges, but a
language-only detector will overfit to writing style and can confuse routine
engineering vocabulary with autonomous behavior. AgentTrace therefore requires
relational evidence and combines semantics with typed artifacts, protocol,
temporal, identity, graph, provenance, and benign-workflow controls.
