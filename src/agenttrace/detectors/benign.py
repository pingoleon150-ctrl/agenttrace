from __future__ import annotations

import re

from agenttrace.models import Observation, Signal

KNOWN_BOTS = {
    "dependabot[bot]",
    "renovate[bot]",
    "github-actions[bot]",
    "codecov[bot]",
    "pre-commit-ci[bot]",
    "mergify[bot]",
    "snyk-bot",
}
AUTOMATION_RE = re.compile(r"(?:release|ci|build|deploy|mirror|sync|dependency|version bump)", re.I)


def detect_benign_automation(observations: list[Observation]) -> list[Signal]:
    if not observations:
        return []
    known = sum(1 for o in observations if o.actor.lower() in KNOWN_BOTS or o.actor.lower().endswith("[bot]"))
    automated_text = sum(1 for o in observations if AUTOMATION_RE.search(o.text or ""))
    known_fraction = known / len(observations)
    text_fraction = automated_text / len(observations)
    score = min(1.0, 0.75 * known_fraction + 0.35 * text_fraction)
    if score < 0.20:
        return []
    return [Signal(
        family="benign",
        name="known_or_likely_automation",
        score=score,
        observation_ids=[o.source_event_id for o in observations],
        evidence=[f"known_bot_fraction={known_fraction:.2f}", f"automation_text_fraction={text_fraction:.2f}"],
    )]
