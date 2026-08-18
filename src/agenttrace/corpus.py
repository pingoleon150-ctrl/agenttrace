from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agenttrace.calibration import fit_presence_likelihood_ratios
from agenttrace.models import Observation
from agenttrace.pipeline import analyze_cluster, analyze_observations


def evaluate_labeled_corpus(
    observations_path: str | Path,
    labels_path: str | Path,
    threshold: float = 0.60,
) -> dict[str, Any]:
    observations = _load_observations(observations_path)
    labels = json.loads(Path(labels_path).read_text(encoding="utf-8"))
    cases = []
    rows = []
    seen_events: set[str] = set()
    for cluster in labels.get("clusters", []):
        event_ids = list(cluster["event_ids"])
        overlap = seen_events.intersection(event_ids)
        if overlap:
            raise ValueError(f"label leakage: events occur in multiple scenarios: {sorted(overlap)}")
        seen_events.update(event_ids)
        missing = [event_id for event_id in event_ids if event_id not in observations]
        if missing:
            raise ValueError(f"missing labeled observations in {cluster['id']}: {missing[:5]}")
        bundle = analyze_cluster(
            str(cluster["id"]), [observations[event_id] for event_id in event_ids], threshold
        )
        names = {signal.name for signal in bundle.signals if signal.family != "benign"}
        cases.append((str(cluster["label"]), names))
        rows.append(
            {
                "id": cluster["id"],
                "label": cluster["label"],
                "scenario": cluster.get("scenario"),
                "reviewable": bundle.score.reviewable,
                "score": bundle.score.score,
                "confidence": bundle.score.confidence,
                "signals": sorted(names),
                "reasons": bundle.score.reasons,
            }
        )
    positives = [row for row in rows if row["label"] == "pos"]
    controls = [row for row in rows if row["label"] != "pos"]
    tp = sum(row["reviewable"] for row in positives)
    fp = sum(row["reviewable"] for row in controls)
    end_to_end = analyze_observations(list(observations.values()), threshold=threshold)
    reviewable_event_sets = [
        {item.source_event_id for item in bundle.observations}
        for bundle in end_to_end
        if bundle.score.reviewable
    ]
    for row, cluster in zip(rows, labels.get("clusters", []), strict=True):
        expected = set(cluster["event_ids"])
        row["end_to_end_reviewable"] = any(
            events.issubset(expected) and len(events) >= min(2, len(expected))
            for events in reviewable_event_sets
        )
    end_tp = sum(row["end_to_end_reviewable"] for row in positives)
    end_fp = sum(row["end_to_end_reviewable"] for row in controls)
    return {
        "evaluation_unit": "labeled_scenario",
        "warning": (
            "Synthetic in-sample results measure regression behavior, not field prevalence or "
            "production probability. Use an independent, substantially larger negative corpus."
        ),
        "counts": {
            "observations": len(observations),
            "scenarios": len(rows),
            "positive_scenarios": len(positives),
            "control_scenarios": len(controls),
        },
        "metrics": {
            "pipeline_clusters": len(end_to_end),
            "pipeline_reviewable_clusters": len(reviewable_event_sets),
            "true_positives": end_tp,
            "false_negatives": len(positives) - end_tp,
            "false_positives": end_fp,
            "true_negatives": len(controls) - end_fp,
            "recall": end_tp / len(positives) if positives else None,
            "false_positive_rate": end_fp / len(controls) if controls else None,
        },
        "oracle_cluster_metrics": {
            "true_positives": tp,
            "false_negatives": len(positives) - tp,
            "false_positives": fp,
            "true_negatives": len(controls) - fp,
            "recall": tp / len(positives) if positives else None,
            "false_positive_rate": fp / len(controls) if controls else None,
        },
        "presence_likelihood_ratios": fit_presence_likelihood_ratios(cases),
        "scenarios": rows,
    }


def _load_observations(path: str | Path) -> dict[str, Observation]:
    result: dict[str, Observation] = {}
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            observation = Observation.model_validate_json(line)
            if observation.source_event_id in result:
                raise ValueError(
                    f"duplicate source_event_id at line {line_number}: {observation.source_event_id}"
                )
            result[observation.source_event_id] = observation
    return result
