# Signal catalog

This catalog captures current and proposed detection ideas. A signal is not an attribution claim. Each item should eventually have a detector, negative controls, and evaluation data.

## Implemented

### Protocol markers

Examples: task IDs, worker IDs, ACK/NACK semantics, heartbeat/status messages, retry counters, sequence numbers, checkpoints, queues, nonces, public-key fingerprints.

Risk: ordinary distributed systems use the same vocabulary. Treat as supporting evidence only.

### Rare artifact propagation

Track rare tokens, hashes, code fingerprints, long identifiers, and URLs that appear *inside content* and subsequently occur under another actor.

Important: provenance URLs are never artifacts. A GitHub issue URL used only to identify the source must not create a shared-artifact edge.

### Rapid cross-actor handoff

Measure latency when activity alternates between actors inside the same candidate cluster.

Risk: CI and active human teams can also be fast.

### Periodicity

Look for repeated intervals consistent with scheduled polling or worker loops.

Risk: cron jobs and release automation are strong negatives.

### Coordination graph topology

Construct actor/event/artifact/repository graphs and score reciprocal actor edges, fan-out, strongly connected actor groups, and shared-artifact edges.

### Explicit identity markers

Correlate public worker IDs, key fingerprints, public keys, and related identifiers reused across pseudonymous actors.

Boundary: do not deanonymize people. The output is a pseudonymous cluster.

### Benign automation suppression

Down-rank known bot identities and automation vocabulary.

## High-priority proposed signals

### Artifact diffusion velocity

Instead of asking only whether an artifact is reused, measure how quickly it moves from actor A to B to C. Compare against the baseline diffusion of snippets and URLs in human OSS communities.

### Novelty-weighted artifacts

An artifact appearing thousands of times on GitHub is weak evidence. A token or error fingerprint observed only a handful of times is stronger. Maintain approximate global frequency estimates so rarity becomes part of artifact weight.

### Task/result pairing

Identify a request-like observation followed by an actor change and a result-like observation referencing the same rare artifacts or task identifier.

### Fan-out / fan-in motifs

Detect patterns where one actor distributes multiple tasks and several actors return results to the same actor or thread.

### State-continuity chains

Detect a unique checkpoint or continuation marker that persists when the visible actor identity changes.

### Cross-repository continuation

Find rare coordination artifacts that leave one repository and appear in another shortly afterward.

### Cross-platform continuation

Generalize the previous idea across GitHub, forums, package registries, mailing lists, and other public datasets.

### Tool-output fingerprints

Agents may paste distinctive tool output, stack traces, environment messages, or formatting. Hash normalized output fragments and measure reuse across actors.

### Error-driven coordination

A worker reports a rare error; another actor later posts a targeted workaround and a third uses the corrected artifact. The useful signal is the causal-looking sequence, not the error text alone.

### 24x7 continuity

Model activity distributions across local time, but only at cluster level. Individual global OSS maintainers and bots make this a weak signal by itself.

### Identity churn

Measure how often the apparent actor changes while unique state/artifact continuity remains high.

### Structural message similarity

Compare message schemas rather than prose. Repeated JSON keys, field order, status enums, task envelopes, and result schemas may reveal a shared coordination protocol.

### Protocol version evolution

Track whether several actors begin using a new field, status value, or schema version shortly after one actor introduces it.

### Coordinated retry behavior

Detect multiple actors changing behavior after a shared failure condition, while avoiding implementation details that would facilitate covert-channel design.

### Temporal graph motifs

Move beyond static graphs by requiring edge order: delegate -> acknowledge -> result -> aggregate, or artifact A -> actor B -> artifact B -> actor C.

### Benign ecosystem fingerprinting

Build explicit profiles for Dependabot, Renovate, Actions, release bots, mirrors, package bots, and major CI patterns so the system learns what *not* to escalate.

## Learned-model ideas for later phases

Do not start here. First accumulate a reproducible labeled corpus.

- anomaly detection over temporal/graph features;
- graph embeddings for coordination motifs;
- sequence models over event types and actor changes;
- calibrated semantic classifiers for delegation/state-transfer language;
- supervised benign-automation classifier;
- weak supervision from deterministic signals;
- active learning driven by analyst review outcomes.

## Privacy-preserving direction

Evaluate a metadata-only detector using timestamps, actor pseudonyms, repository/thread relationships, and artifact hashes without retaining prose. If competitive, this could become the preferred high-volume first stage.
