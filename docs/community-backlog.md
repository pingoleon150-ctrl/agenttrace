# Community backlog

These are candidate issues to open once the public repository is online.

## P0 — Evaluation before sophistication

### Build a benign GitHub automation corpus

Collect reproducible public examples of Dependabot, Renovate, GitHub Actions, release bots, mirrors, and high-frequency human maintainer threads. Define labels and sampling rules.

Suggested labels: `dataset`, `false-positive`, `good first issue`.

### Add a controlled multi-agent simulator

Create a local mock Git/forum environment where synthetic workers can delegate tasks, acknowledge work, propagate artifacts, rotate identities, and recover state. The simulator exists only to generate labeled defensive evaluation data.

Suggested labels: `research`, `dataset`.

### Add precision-at-threshold evaluation

Given labeled positive and negative clusters, report precision, recall, false positives per million observations, calibration, and time-to-first-detection.

Suggested labels: `research`, `evaluation`.

## P1 — Better GitHub coverage

### Expand PR review-thread collection

Add public pull-request review comments and review submissions so code-review coordination is reconstructed beyond top-level issue comments.

Suggested labels: `collector`, `github`.

### Add commit and diff artifact extraction

For candidate repositories only, retrieve public commit messages/diffs and fingerprint rare code/error artifacts without executing repository content.

Suggested labels: `collector`, `artifact`.

### Add release / tag metadata collector

Evaluate whether release notes and tags expose persistent coordination markers useful for state-continuity research.

Suggested labels: `collector`, `github`.

### Build GitHub rate-limit scheduler and checkpoints

Persist cursors/checkpoints, respect primary/secondary limits, use conditional requests where appropriate, and prevent duplicate expansion of already-analyzed threads.

Suggested labels: `collector`, `reliability`.

## P1 — Artifact intelligence

### Global artifact-frequency estimator

Estimate how rare an artifact is across the available corpus. Down-weight common URLs/tokens and up-weight novel values.

Suggested labels: `artifact`, `research`.

### Artifact diffusion detector

Model actor A -> artifact -> actor B -> derived artifact -> actor C, including propagation latency and repository transitions.

Suggested labels: `artifact`, `graph`.

### Normalized tool-output fingerprinting

Research normalization strategies for stack traces/tool output so superficial timestamps/paths do not prevent matching while preserving enough specificity to avoid false positives.

Suggested labels: `artifact`, `research`.

## P1 — Graph and temporal research

### Temporal motif miner

Represent ordered motifs such as delegate -> ACK -> result -> aggregate rather than relying on static connectivity.

Suggested labels: `graph`, `temporal`, `research`.

### Fan-out/fan-in detector

Detect coordinator-like nodes that distribute tasks to multiple actors and later receive results.

Suggested labels: `graph`, `detector`.

### Activity baseline by ecosystem

Compare timing against repository-specific and actor-specific baselines so highly active OSS projects are not penalized merely for being fast.

Suggested labels: `temporal`, `false-positive`.

## P2 — Cross-platform

### RSS/Atom public forum collector

Define a generic feed collector with canonical thread/reply relationships and provenance.

Suggested labels: `collector`, `good first issue`.

### Cross-source artifact index

Index rare artifact hashes across sources and create candidate links only when rarity and temporal ordering justify expansion.

Suggested labels: `artifact`, `architecture`.

### Probabilistic pseudonymous entity resolution

Link public identities based on explicit/public markers without attempting real-world deanonymization.

Suggested labels: `identity`, `privacy`, `research`.

## P2 — Analyst experience

### Evidence timeline CLI export

Generate a compact Markdown/JSON timeline showing actors, event types, artifacts, detector hits, and provenance links.

Suggested labels: `analyst-ui`, `good first issue`.

### Graph export

Export GraphML and a small JSON graph schema for Gephi/Cytoscape/browser visualization.

Suggested labels: `graph`, `analyst-ui`.

### False-positive feedback format

Define a portable review record that marks a cluster benign/suspicious/unknown and records the analyst reason, enabling later calibration.

Suggested labels: `evaluation`, `analyst-ui`.
