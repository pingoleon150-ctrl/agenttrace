# Detection model

## Signal hierarchy

| Family | Example | Default evidentiary value |
|---|---|---|
| Artifact propagation | rare token/code/hash reused by another identity | High |
| Graph | delegation/fan-out/result aggregation | High |
| Identity | same public key/fingerprint/worker token | High |
| Temporal | rapid or strongly periodic handoffs | Medium-high |
| Protocol | task IDs, ACK, heartbeat, retry, TTL | Medium |
| Semantic | roles, state transfer, delegation language | Medium |
| Generic AI prose | stylistic "LLM-like" text | Low; intentionally unused |

## Evidence bundle contract

Every candidate cluster must preserve:

- exact public URLs;
- original timestamps;
- source event IDs;
- actor handles as observed;
- detector outputs;
- extracted artifacts;
- score and benign-automation penalty;
- explicit uncertainty statement.

## False-positive classes

The negative corpus must heavily represent:

- Dependabot / Renovate;
- GitHub Actions;
- release automation;
- mirrored repositories;
- package/version bots;
- support automation;
- high-frequency human OSS collaboration;
- generated-code repositories;
- distributed build/test systems.

## Evaluation metrics

Prioritize:

1. precision at analyst-review threshold;
2. false positives per million observations;
3. campaign-level recall;
4. time-to-first-detection;
5. calibration error;
6. evidence completeness.

Raw message classification accuracy is not a primary metric.
