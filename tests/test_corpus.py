from pathlib import Path

from agenttrace.corpus import evaluate_labeled_corpus


def test_bundled_synthetic_corpus_is_a_regression_fixture():
    root = Path(__file__).parents[1] / "corpus" / "synthetic-v2"
    report = evaluate_labeled_corpus(root / "observations.jsonl", root / "labels.json")
    assert report["counts"] == {
        "observations": 128,
        "scenarios": 8,
        "positive_scenarios": 4,
        "control_scenarios": 4,
    }
    assert report["metrics"]["true_positives"] == 4
    assert report["metrics"]["false_positives"] == 0
