# Query strategy

Search engines are candidate generators. They do not decide whether coordination exists.

## Seed -> expand -> correlate -> verify

```text
seed query
   |
   v
GitHub / grep.app / historical dataset
   |
   v
candidate repo + thread + artifact
   |
   v
expand neighboring public observations
   |
   v
build actor/artifact/time graph
   |
   v
score independent signals
   |
   v
verify evidence against canonical public source
```

## Query families

Maintain small, high-specificity combinations rather than giant OR queries.

Protocol examples:

```text
"task_id" "worker_id"
"task_id" "ACK"
"heartbeat" "checkpoint"
"retry_count" "worker"
```

State examples:

```text
"resume_token"
"continuation_token"
"checkpoint" "nonce"
```

Integrity examples:

```text
"signature" "task_id"
"public key" "worker_id"
```

Runtime examples:

```text
"sandbox" "task_id"
"coordinator" "worker" "result"
```

These strings are broad research seeds, not signatures of malicious behavior.

## Rarity expansion

When a candidate contains an unusual token or artifact:

1. search exact artifact globally;
2. record repository/path/thread occurrences;
3. order by time;
4. identify actor transitions;
5. retrieve surrounding context;
6. score the reconstructed trajectory.

## Rate-limit strategy

Prefer historical/bulk datasets for broad candidate generation and reserve live GitHub API calls for thread expansion and provenance verification. Cache source IDs locally so reruns do not repeatedly process the same observations.
