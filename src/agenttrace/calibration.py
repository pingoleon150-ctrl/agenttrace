from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from agenttrace.models import Signal


@dataclass(frozen=True)
class CalibrationProfile:
    """Presence-only likelihood ratios learned from labeled, independent scenarios."""

    likelihood_ratios: dict[str, float]
    prior_probability: float = 0.001
    exceptional_lr: float = 100.0
    corpus_id: str = "unknown"

    @classmethod
    def load(cls, path: str | Path) -> CalibrationProfile:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            likelihood_ratios={
                str(key): float(value) for key, value in payload["likelihood_ratios"].items()
            },
            prior_probability=float(payload.get("prior_probability", 0.001)),
            exceptional_lr=float(payload.get("exceptional_lr", 100.0)),
            corpus_id=str(payload.get("corpus_id", "unknown")),
        )

    def evidence(self, signals: list[Signal]) -> tuple[float, float, list[str]]:
        selected = {signal.name for signal in signals if signal.family != "benign"}
        contributions = {
            name: self.likelihood_ratios[name]
            for name in selected
            if name in self.likelihood_ratios and self.likelihood_ratios[name] > 0
        }
        log_lr = sum(math.log(value) for value in contributions.values())
        prior_odds = self.prior_probability / (1.0 - self.prior_probability)
        posterior_odds = prior_odds * math.exp(min(log_lr, 700.0))
        posterior = posterior_odds / (1.0 + posterior_odds)
        reasons = [f"lr:{name}={value:.2f}" for name, value in sorted(contributions.items())]
        return log_lr, posterior, reasons


def fit_presence_likelihood_ratios(
    cases: list[tuple[str, set[str]]], smoothing: float = 0.5
) -> dict[str, float]:
    """Fit signal-presence LRs with Jeffreys smoothing at scenario level."""
    positives = [signals for label, signals in cases if label == "pos"]
    negatives = [signals for label, signals in cases if label != "pos"]
    if not positives or not negatives:
        raise ValueError("calibration requires positive and negative scenarios")
    names = set().union(*(signals for _label, signals in cases))
    ratios: dict[str, float] = {}
    for name in names:
        p_signal = (sum(name in signals for signals in positives) + smoothing) / (
            len(positives) + 2 * smoothing
        )
        p_control = (sum(name in signals for signals in negatives) + smoothing) / (
            len(negatives) + 2 * smoothing
        )
        ratios[name] = p_signal / p_control
    return ratios
