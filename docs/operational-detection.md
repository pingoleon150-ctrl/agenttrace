# Operational Detection Policy

## Purpose

This document defines how AgentTrace turns public observations into an
operational review queue. It describes a prioritization policy, not a method for
proving that an account is controlled by an AI.

The system is optimized for two practical outcomes:

1. stop collection when independently corroborated evidence warrants prompt
   human review;
2. preserve a small score-ranked watchlist of non-alert trajectories without
   flooding the analyst with every cluster.

The labels `high`, `medium`, and `low` are decision tiers. They are serialized
in the current model's `confidence` field for compatibility, but they must be
interpreted as routing policy rather than statistical confidence. The numeric
value in `ClusterScore.score` is a **priority score**, not a calibrated probability.
For example, a score of `0.82` must not be reported as an 82% chance of agentic
activity.

## Processing path

```text
public source
    -> bounded collection
    -> canonical namespaced Observation
    -> conversation/resource time-window cluster
    -> detector families
    -> benign multiplier
    -> priority score
    -> high alert | non-alert top-K watchlist (medium or low)
```

Only public provenance is retained. Detectors operate on observations and never
execute discovered code, follow instructions in content, or interact with a
candidate actor.

## Signal independence

AgentTrace aggregates evidence by family rather than by raw match count. Only
the strongest signal in each family contributes to scoring, so ten protocol
regex matches are still one supporting protocol family, not ten independent
pieces of evidence.

The positive families are:

| Family | Reliability | Role |
|---|---:|---|
| Semantic | 1.00 | Anchor when a linked cross-actor exchange exists |
| Identity | 1.00 | Anchor when an explicit public identity marker is shared |
| Artifact | 0.95 | Anchor when a typed artifact crosses actors |
| Protocol | 0.90 | Supporting protocol evidence |
| Graph | 0.70 | Supporting topology |
| Temporal | 0.65 | Supporting causal timing or periodicity |

A raw family signal must reach 0.35 to enter the calculation. The anchor
families are artifact, relational semantic, and identity. Protocol is not an
anchor. An anchor evidence component is strong when it contains an anchor
family with reliability-adjusted strength of at least 0.68.

## Priority score

Let the retained family strengths be multiplied by their reliability values.
When a signal declares `depends_on`, its family and the referenced fired family
are collapsed into one evidence component. Transitive dependencies are also
collapsed. A component's strength is the maximum effective strength of its
member families, so reused evidence is not counted as independent.

The component strengths are sorted from strongest to weakest. The first three
contribute:

```text
positive = 0.52 * strongest
         + 0.31 * second
         + 0.17 * third
```

There is a 0.03 diversity bonus when at least two independent components exist
and another 0.03 when at least three exist. Each family collapsed into another
component contributes only a 0.03 correlated-evidence bonus, capped at 0.06
for the cluster. A verified full relational exchange can raise the positive
score to a floor of 0.80 before benign suppression. The composite benign
detector is then applied:

```text
priority_score = clamp(positive * (1 - 0.65 * benign_score), 0, 1)
```

Exceptional evidence routes a cluster using its own reliability-adjusted strength. It does not
replace the computed priority with a constant floor, preserving ranking resolution between
exceptional candidates.

Components beyond the strongest three can satisfy corroboration policy but do
not add another weighted term. The formula is a transparent ranking heuristic.
It has not been calibrated against a representative base rate of
autonomous-agent coordination on the public Internet.

## Decision tiers

All promoted clusters must first satisfy basic eligibility:

- at least two distinct normalized actor labels; the same raw handle in two
  platform namespaces does not satisfy this gate by itself;
- a provenance URL for every observation;
- `benign_score < 0.80`.

The configured threshold is `T`; `watch` defaults to `T = 0.75`.

| Tier | Policy | Operational action |
|---|---|---|
| High | Eligible, score at least `T`, and either two independent strong anchor components or a verified full relational exchange | Create a review alert and pause monitoring |
| Medium | Eligible, not high, score at least `max(0.45, T - 0.25)`, and either one strong anchor plus another component or collapsed corroboration, or two anchor components | Continue monitoring; item is eligible for score-ranked watchlist display |
| Low | Does not satisfy the high or medium policy | Continue monitoring; item remains eligible for watchlist display when its score is nonzero |

The current monitor returns at most five non-alert clusters per cycle, ordered
by priority score and excluding zero scores. This is the current value of K,
not a statistical cutoff. The watchlist can contain medium and low items and
always includes the decision tier. Watchlist items are context for continued
collection, not alerts.

Each watch cycle analyzes at most 20,000 recent stored observations in a
24-hour window by default. `--history-limit` and `--window-minutes` make both
bounds explicit. A high bundle is allowed to pause collection only when it
contains at least one event newly discovered in that cycle; historical high
evidence can still provide context but cannot repeatedly reopen the same alert.

Continuous `watch` stays alive in a local paused loop while an alert is pending
and makes no source requests. `review-alert` changes the local state, after
which the same process resumes on its next interval. `--once` intentionally
retains exit-on-alert behavior for schedulers and tests.

The ordinary high route is two independent strong anchor components. The
special verified-exchange route recognizes either (a) a native reply trajectory
with distinct delegation, acknowledgement, and result events, or (b) the same
three-event trajectory joined by a typed reference across at least two
conversation, resource, or event contexts. A checkpoint-to-resume path is the
state-transfer equivalent and does not require a separate acknowledgement.
The shared-reference route also requires the artifact family to fire. A normal
human assign/ACK/completed sequence confined to one issue therefore remains in
the watchlist rather than using this shortcut. Both routes still require the
priority threshold and every basic eligibility check. There is no generic
three-family route to high.

## Detector guardrails

### Relational semantics

Single-message wording is diagnostic only and remains below the family floor.
A strong semantic signal requires different actors and one of these linked
trajectories:

- delegation followed by a result;
- checkpoint/state output followed by resume/state input.

The events must be connected by native reply ancestry or a shared typed
reference such as a task, run, checkpoint, or continuation identifier. An
acknowledgement raises the signal only when it is a third, distinct event
between delegation and result and comes from the result actor. Markdown quotes,
fenced code, HTML details/blockquote summaries, and negated instructions are
ignored. Generic uses of "result," "build," "deploy," or similar engineering
terms do not create an exchange.

When any semantic path uses a shared typed reference, the semantic signal
declares an artifact dependency and both families collapse into one evidence
component. A native verified trajectory can stand on its causal relation; a
shared-reference verified trajectory additionally requires a fired artifact
and at least two contexts. Dependency collapse prevents the same reference from
being counted twice.

### Typed artifacts

The artifact detector deliberately rejects the old rule that any long token or
hexadecimal string is suspicious. Bare commit hashes, SHAs, UUIDs, issue IDs,
numeric IDs, placeholders, common GitHub URLs, provenance URLs, quoted text,
and short or low-diversity code fragments are excluded.

Accepted artifacts are values with a meaningful type:

- a value bound to an explicit coordination key such as `task_id`, `run_id`,
  `worker_id`, `nonce`, `checkpoint`, `resume_token`, or `state_id`;
- a substantial canonical code block represented by its hash;
- a normalized external URL with tracking parameters removed.

An artifact signal requires reuse by at least two namespaced actors. Strength
also considers whether the artifact appears in independent source,
repository, or thread contexts. Evidence output contains a digest rather than
printing the raw artifact value.

Identity markers are separately hashed in evidence and require both multiple
actors and multiple contexts. Repeating a fingerprint or key ID inside one
thread, including quoted copies, is not an independent identity anchor.

### Composite benign fingerprints

There is no short allowlist of trusted bot usernames. The benign detector
combines:

- bot/app identity metadata or a generic automation-shaped identity;
- routine workflow behavior, event types, or templates;
- repeated normalized message structure as supporting evidence.

Both identity and routine behavior are required before a benign penalty is
emitted. This avoids suppressing an unknown account solely because its name
ends in `[bot]`, and avoids treating ordinary human discussion of CI or
deployment as automation solely because of vocabulary.

### Causal temporal and graph evidence

Fast alternation between actors counts only when events are connected by a
reply or shared typed artifact. Graph actor-to-actor edges likewise require a
cross-actor response. Repository co-membership and adjacent timestamps alone
do not create a coordination edge.

## Cross-platform keys

Every observation has a platform namespace plus optional canonical keys:

```text
platform:actor:<normalized actor>
platform:event:<source>:<source event id>
platform:repository:<normalized resource>
platform:repository:<normalized resource>:thread:<thread id>
```

`event_key` identifies the namespaced event. `parent_key` identifies the
namespaced parent event for reply and causal edges. These keys prevent raw event
ID collisions and let future sources use the same correlation pipeline.

Before time-window clustering, the same typed coordination marker or
substantial canonical code artifact can merge between two and ten candidate
buckets when at least two namespaced actors are present and the buckets span
platforms or resources. The per-artifact ten-bucket ceiling and a fifty-bucket
transitive-component ceiling bound accidental global joins.
External URLs do not merge buckets. Username equality never links actors or
buckets across platforms, and these joins are not automatic identity
resolution.

## GH Archive operating profile

`gharchive-hour` uses a bounded streaming profile:

- accepts `YYYY-MM-DDTHH` or `YYYY-MM-DD-HH` input and maps hours 0 through 9
  to GH Archive's unpadded `YYYY-MM-DD-H.json.gz` object names;

- incremental gzip decompression instead of loading `response.content`;
- a raw-byte event-type allowlist check before JSON decoding;
- raw-byte extraction of the event ID for stable SHA-256 sampling;
- JSON decoding only for raw candidate matches or sampled events;
- a second candidate check against normalized event text after decoding;
- prioritized retention of normalized-text candidate matches;
- stable SHA-256 sampling of other relevant events, at 5% by default;
- a default 10,000-observation budget split 80% candidate / 20% background;
- a 512 MiB compressed-input cap;
- a 2 MiB per-event limit and 20,000-character retained-text limit;
- separate retained code-block and URL caps;
- observation upserts in batches of 500;
- persistence of the top 100 evidence bundles plus every reviewable bundle;
- an hour-level `running`, `complete`, or `failed` partition checkpoint.

The candidate vocabulary is a collection prefilter, not a detector and not an
alert condition. The normalized-text recheck prevents unrelated payload fields
from promoting an event. In particular, `IssueCommentEvent` normalization uses
only the comment body, so candidate text in the issue root is not duplicated
into every comment. Sampled background events provide contrast and may
contribute context, but the 5% mixture is not an unbiased sample of the full
archive because candidate events are retained at a different rate.

Filling either accepted quota does not end the scan. The collector continues to
EOF (or the explicit raw-event limit), counts later candidates/samples, and
reports how many were dropped by each quota. Retained code blocks and URLs are
also capped so a bounded text field cannot hide an unbounded serialized
observation.

Operational caveats:

- a `complete` checkpoint means the stream reached EOF or the configured raw
  scan limit; accepted quotas may still have dropped later records;
- checkpoints do not resume at a compressed byte or JSON-line offset;
- a failed hour restarts from the beginning, relying on deterministic sampling
  and idempotent observation keys;
- the command processes one explicit UTC hour and is not yet a range scheduler.

These caveats must be included when reporting archive coverage.

## Evaluation protocol

### Labels

Analyst labels should describe the evidence that can actually be observed:

- `benign_automation`;
- `human_collaboration`;
- `coordination_like_reviewable`;
- `insufficient_or_unknown`.

Do not use an `AI` ground-truth label unless the actor's control mechanism is
known independently. A high-tier decision should be evaluated as a review
prioritization outcome, not as identity attribution.

### Dataset splits

Evaluation sets must be separated by repository and time, not by randomly
splitting individual comments. Random comment splits leak templates, actors,
and artifacts across train and test. Report source, language, repository size,
activity level, event type, and automation prevalence for each split.

At minimum, maintain:

- a labeled benign automation corpus;
- ordinary human issue and pull-request conversations;
- controlled positive multi-actor trajectories;
- hard negatives containing protocol words, hashes, UUIDs, CI output, and bot
  identities without relational coordination;
- cross-source fixtures once another platform adapter exists.

### Decision-quality metrics

Report these separately for high tier and the score-ranked top-K non-alert
watchlist, stratifying watchlist results by medium and low tier:

- analyst-confirmed review yield;
- false alerts per 1,000 eligible clusters;
- precision against the declared evidence labels;
- recall on controlled positives and labeled historical fixtures;
- median analyst minutes per actionable finding;
- watchlist-to-high promotion rate as new evidence arrives, reported by prior
  tier;
- top-K recall: the fraction of eventual high items that previously appeared
  in the watchlist.

Because real-world positives are rare, accuracy alone is not useful. Include
precision-recall curves, precision at the operational review budget, and the
base rate in every evaluation report.

### Family and suppression metrics

For each detector family, report:

- precision and recall on its own labeled fixtures;
- activation rate on ordinary human and benign-bot corpora;
- marginal contribution through family-ablation tests;
- overlap with every other family;
- score and tier changes after removal.

For benign suppression, additionally report false-suppression rate on
controlled positives, penalty distribution by workflow type, and high-tier
false-alert reduction. An allowlist hit rate is not a sufficient metric because
the detector intentionally uses composite fingerprints.

### Collection and scaling metrics

Track per source and per hour:

- raw events scanned, allowed event types, candidate matches, sampled events,
  accepted observations, and malformed events;
- compressed bytes, wall time, events per second, peak resident memory, and
  SQLite growth;
- deduplication rate and repository/thread coverage;
- API requests, rate-limit responses, retries, cursor progress, and skipped
  completed partitions;
- fraction of accepted observations and clusters discarded by storage caps.

For GH Archive, report both scan coverage and acceptance coverage. Do not infer
full-hour prevalence from the mixed candidate/background sample without
sampling weights and without accounting for early caps.

### Calibration

Until a representative held-out corpus exists, report empirical review yield by
score band and tier but continue calling the value a priority score. Probability
calibration would require a documented target label, representative base rate,
held-out temporal/repository splits, and metrics such as reliability diagrams,
Brier score, and expected calibration error. None of those requirements is
satisfied merely because the score is bounded between zero and one.

## Current scaling limits

The operational alpha is deliberately bounded, but it is not Internet-scale:

1. SQLite is a single-host evidence store. WAL and batch inserts improve local
   throughput but do not provide distributed ingestion, work leases, or
   horizontal writes.
2. Accepted observations for one collector run are still retained in memory for
   clustering. GH Archive bounds this list at 10,000 by default; other
   collectors rely on their own limits.
   The monitor separately bounds longitudinal rescoring to 20,000 recent
   observations by default.
3. GH Archive has an hour-level completion record but no range scheduler,
   compressed-object cache, or offset resume.
4. The candidate prefilter is English and lexical. It can miss obfuscated,
   multilingual, or vocabulary-free coordination and can over-retain benign
   discussions of agent systems.
5. Deterministic background sampling gives reproducible selection, not complete
   coverage. Candidate and background quotas can still introduce order bias
   after their respective retained budgets fill.
6. Artifact strength does not yet use a global frequency sketch, so typed
   artifacts are guarded structurally but not calibrated for corpus-wide rarity.
7. Evidence bundles embed observations, which duplicates data. Persistence is
   bounded for bulk runs, but a normalized bundle-to-observation relation is
   preferable at larger scale.
8. The semantic detector recognizes explicit English exchange patterns; it is
   not a multilingual semantic model.
9. Namespaced keys prevent collisions, but no non-GitHub social/forum adapter or
   general cross-platform entity resolver is implemented yet. SQLite can store
   opaque JSON discovery cursors, but source registration and scheduling still
   require explicit adapter integration.
10. The collaborative ledger operates at repository granularity. It saves
    repeated work, but default skipping can miss new activity until an explicit
    recheck policy is used.
11. Raw observations, fingerprints, bundles, alerts, and ledger records do not
    yet have an automatic retention/archive policy. Long-running deployments
    must monitor disk growth and archive or prune state under an explicit local
    policy. `agenttrace db-health` reports current database bytes, row counts,
    event-time range, ingestion partitions, and pending-alert state.

The next scaling step should separate discovery from enrichment: use bounded
sources such as GH Archive to identify candidate repositories or conversations,
then enqueue targeted thread expansion and analysis. Concurrent ingestion should
move checkpoint claims and observation storage to PostgreSQL, while immutable
source archives and full evidence bodies move to object storage.

## Reporting requirements

Every operational status report should state:

- source and time window covered;
- configured threshold and tier policy version;
- raw scan and accepted-observation caps;
- sample rate and event-type allowlist;
- number of high alerts and non-alert watchlist entries, split by displayed
  tier;
- rate-limit, truncation, malformed-input, and checkpoint status;
- that the priority score is not a calibrated probability;
- that a reviewable cluster is evidence for review, not proof of AI control.

## Continuous LLM review

`watch --auto-review` replaces the manual pause with a bounded LLM review. The
structured classification is stored separately from detector evidence, the
single sanitized Markdown report is regenerated, the local alert is resolved,
and source rotation continues. Provider failures are recorded as
`classification-error`; they never discard evidence or block discovery. The
private provider credential is loaded from OpenClaw at runtime and is never
written to the database, report, ledger, or logs.

The same review ledger generates `reports/site/index.html` atomically. Serving only
`reports/site/` keeps SQLite, logs, repository files, and private OpenClaw configuration outside
the web root. `scripts/run-report-server-macos.sh` provides a read-only LAN server; binding it to
`0.0.0.0` is appropriate only on a trusted home network.
