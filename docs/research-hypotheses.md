# Research hypotheses

This file is the research backlog. Each hypothesis should eventually have a reproducible corpus, detector, and false-positive study.

## H1 — Rare artifact propagation is stronger than AI-writing style

If actor B reuses a rare token, code fragment, error fingerprint, URL, nonce, or public key shortly after actor A exposes it, the sequence is more informative than either message's prose style.

Experiment: compare artifact-diffusion precision across human OSS teams, bots, and controlled multi-agent simulations.

## H2 — Agent handoffs have a distinctive temporal distribution

Autonomous workers may produce unusually short or regular task-to-result latencies. Humans and CI systems provide important negative controls.

Experiment: model cross-actor gap distributions conditioned on repository, time of day, and known-bot status.

## H3 — Coordination creates reusable graph motifs

Leader/worker fan-out, queue consumption, repeated ping-pong, result aggregation, and checkpoint recovery should appear as small temporal motifs independent of natural language.

Experiment: motif mining over labeled synthetic swarms and known automation ecosystems.

## H4 — State persistence can survive identity churn

An agent may reappear under a different public identity but continue from a unique checkpoint, key, nonce, URL, or artifact.

Experiment: controlled identity rotation with and without explicit state markers.

## H5 — Cross-platform continuation is high-value evidence

The same rare coordination token appearing in a GitHub issue and later in a forum/paste/package artifact may reveal a trajectory that per-platform detectors miss.

Experiment: cross-index candidate retrieval by unique artifact fingerprints.

## H6 — Benign automation is the hardest negative class

The largest practical source of false positives will likely be bots and CI rather than humans.

Experiment: build and version a known-benign automation corpus before training learned models.

## H7 — Coordination can be detected without reading prose

A privacy-preserving detector using only timestamps, graph edges, artifact hashes, and public identity metadata may recover useful coordination signals.

Experiment: compare metadata-only and content-aware models.

## H8 — Deliberately covert agents will shift from textual protocol to side channels

If agents optimize against obvious markers like `task_id` or `ACK`, artifact timing, graph topology, and state propagation should remain partially observable.

Experiment: adversarial synthetic swarms instructed to minimize explicit coordination vocabulary.
