# Contributing to AgentTrace

AgentTrace welcomes defensive research contributions.

## Good first contributions

- add a benign-bot fingerprint with tests;
- add a detector with a clear hypothesis and negative examples;
- add a public-data collector that respects access controls and service terms;
- improve evidence visualization;
- contribute sanitized/reproducible corpora;
- improve graph or temporal analysis.

## Detector contribution contract

A new detector should include:

1. a named signal family;
2. a documented hypothesis;
3. deterministic evidence strings;
4. positive test cases;
5. negative/false-positive test cases;
6. no claim that a single hit proves AI attribution.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
ruff check src tests
```

## Pull requests

Keep PRs focused. Explain what evidence the detector observes, expected false positives, and how the test corpus validates the change.

## Data and privacy

Do not commit private data, credentials, scraped private content, or unnecessary personal information. Public pseudonymous handles may be retained only when needed for reproducible coordination analysis.
