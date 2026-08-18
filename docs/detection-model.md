# Detection model

## Signal hierarchy

Signals have different decision roles. The implementation does not treat a
count of families as independence.

| Family | Example | Decision role | Reliability |
|---|---|---|---:|
| Relational semantics | linked delegation/ACK/result or checkpoint/resume trajectory | Anchor | 1.00 |
| Identity | public key or fingerprint reused by distinct actors and contexts | Anchor | 1.00 |
| Artifact propagation | typed coordination value or substantial code fingerprint reused by another actor | Anchor | 0.95 |
| Protocol | task IDs, ACK, heartbeat, retry, TTL | Supporting | 0.90 |
| Graph | topology built from native reply relationships | Supporting | 0.70 |
| Temporal | rapid or periodic causally linked handoffs | Supporting | 0.65 |
| Generic AI prose | stylistic "LLM-like" text | Intentionally unused | 0.00 |

Bare commit SHAs, UUIDs, issue numbers, arbitrary long strings, GitHub source
URLs, and matching usernames are not coordination artifacts. Semantic paths
must use native reply ancestry or a shared typed reference. Quotes, copied
summaries, and locally negated claims are removed before path construction.

## Decision policy

The numeric value is an operational priority score, not a probability. A high
tier requires complete provenance, at least two distinct normalized actor
labels, a low benign-automation penalty, and one of two routes:

1. two independent strong anchor components; or
2. a verified relational exchange. A native exchange requires a real linked
   trajectory; a cross-context exchange also requires typed-artifact evidence.

Dependencies between families are declared explicitly and collapsed before
combination. Protocol, timing, or graph evidence cannot produce a high alert
without an anchor. Routine automation is suppressed by composite fingerprints
that combine bot/app identity metadata with routine workflow behavior; a bot
name or automation word alone is insufficient.

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
