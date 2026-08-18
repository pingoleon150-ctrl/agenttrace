# GitHub discovery sources

AgentTrace should not depend on a single search backend. Different sources cover different slices of public GitHub activity.

## GitHub REST/Search

Best for canonical metadata and provenance. The MVP uses issue/PR search and optionally code search. Authentication increases practical capacity and is required for the REST code-search endpoint.

Use this source to verify candidate hits found elsewhere.

## GitHub public Events API

Useful for very recent public activity and temporal experiments. It is not a complete historical feed and should not be treated as one.

## GH Archive

GH Archive records GitHub's public event timeline into hourly compressed JSON
files and also exposes a BigQuery public dataset. AgentTrace's
`gharchive-hour` command is a bounded single-hour replay tool. BigQuery or a
distributed candidate-generation job is the practical route for large-scale
temporal/graph research; local hourly replay is for bounded reconstruction and
verification.

Recommended strategy:

```text
BigQuery / distributed archive scan -> coarse candidate generation
                                    -> bounded AgentTrace hourly replay
                                    -> GitHub REST verification
```

## grep.app

A fast public-code search engine useful for discovery. AgentTrace treats it as an experimental adapter because it is a third-party service and its API contract can change.

Recommended use:

```text
seed coordination patterns -> grep.app
                           -> candidate repo/path
                           -> verify through GitHub
```

## Sourcegraph public code

Sourcegraph maintains a public instance/search capability for open-source code. It is useful for analyst exploration and query development. A future adapter should only be added if its supported public API and terms are appropriate for automated research.

## Search strategy

Avoid one giant keyword query. Maintain query families:

- explicit protocol: `task_id`, `worker_id`, `ACK`, heartbeat, checkpoint;
- state continuity: continuation token, resume token, state ID;
- integrity/authentication: nonce, signature, public key, fingerprint;
- agent runtime vocabulary: sandbox, tool call, worker/coordinator;
- rare combinations rather than common single words.

Search is candidate generation, not detection. The detector must reconstruct sequences and evidence after retrieval.
