# Synthetic labeled corpus v2

This directory contains 128 synthetic canonical observations grouped into eight
independent labeled scenarios:

- four positive coordination scenarios (`P5` through `P8`);
- three human-control scenarios (`N1`, `N3`, and `N4`);
- one benign-automation scenario (`N2`).

The data was supplied to the project as a synthetic fixture. Accounts and URLs
are fictional, and provenance uses the reserved `synthetic.invalid` domain.
The generator is intentionally not included in the executable package: the
committed JSONL and labels are the immutable regression fixture.

Run the scenario-level evaluation with:

```bash
agenttrace evaluate-corpus \
  corpus/synthetic-v2/observations.jsonl \
  corpus/synthetic-v2/labels.json
```

Important limitations:

- This is a tiny, synthetic, in-sample regression corpus. Its false-positive
  rate and likelihood ratios are not production estimates.
- `P8` describes two buried rare-token handoffs, but those tokens are not
  present in the supplied observations. The scenario therefore evaluates only
  its continuous multi-actor activity pattern.
- A production calibration requires a held-out corpus with thousands of
  independently sampled human and benign-automation scenarios and a realistic
  deployment base-rate prior.

Labels are joined only by `source_event_id`; the observation records do not
contain their labels.
