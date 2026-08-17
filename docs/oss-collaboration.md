# Open-source collaboration model

AgentTrace should be useful as a research commons rather than a closed detection product.

## Contribution lanes

### Collectors

Adapters for public datasets and APIs. Every collector must document provenance, rate limits, access-control boundaries, and reproducibility.

### Detectors

Small independent signal modules. Each detector should expose evidence, not only a score.

### Corpora

The most valuable community contribution may become labeled negative data: CI bots, dependency bots, release automation, mirrors, and high-frequency human collaboration.

### Research notebooks / experiments

Experiments should graduate into reproducible scripts or tests once the hypothesis stabilizes. Avoid committing large raw datasets directly to Git.

### Analyst UX

Timeline views, graph exploration, evidence comparison, and false-positive feedback are all welcome once the core signal model is stable.

## Suggested issue labels

- `collector`
- `detector`
- `research`
- `false-positive`
- `dataset`
- `graph`
- `temporal`
- `artifact`
- `good first issue`
- `help wanted`
- `privacy`

## Review standard

A contribution is stronger when another researcher can answer:

1. What public observation does this use?
2. Why could it indicate coordination?
3. What benign behavior looks similar?
4. How is evidence preserved?
5. Can the result be reproduced from a versioned corpus?

## Long-term governance

If the project attracts sustained contributors, introduce lightweight RFCs for schema changes, scorer changes, and new high-volume data sources. Detector additions should remain easy; changes to attribution semantics should require broader review.
