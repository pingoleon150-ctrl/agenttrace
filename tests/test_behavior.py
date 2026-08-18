from datetime import UTC, datetime, timedelta

from agenttrace.correlation.trajectories import longitudinal_candidates
from agenttrace.detectors.artifact_reuse import extract_artifacts
from agenttrace.detectors.behavior import detect_behavioral_signals
from agenttrace.models import Observation, Provenance


def observation(index: int, actor: str, text: str, *, hours: float = 0, repo: str = "x/a"):
    started = datetime(2026, 1, 1, tzinfo=UTC)
    return Observation(
        source="test",
        source_event_id=str(index),
        observed_at=started + timedelta(hours=hours),
        event_time=started + timedelta(hours=hours),
        actor=actor,
        event_type="comment",
        text=text,
        repository=repo,
        provenance=Provenance(url=f"https://example.invalid/{index}"),
    )


def test_opaque_cross_actor_exchange_is_exceptional():
    payloads = [
        "DR9FqKxUzQGJ9gjs38QT+kAmpUYPyal7",
        "hkgRtuUFTg5ZuarGkbIqpmGQSgJwPZoD",
        "0U7NS8saZ0wbqSJ9X+/WtCkG5UFZZQSw",
        "9lEWffdObkJEFnq/qGbEqajwwNFeH07i",
        "1V3X3nu+ajRJEJNCbPI0PVehUY4N5Fj2",
        "80mgCQ4ZElf6nBOTv80XsAHgEUgoK8A0",
    ]
    items = [
        observation(i, f"actor-{i % 2}", f"dataset update: {payload}", hours=i / 120)
        for i, payload in enumerate(payloads)
    ]
    signals = detect_behavioral_signals(items)
    signal = next(item for item in signals if item.name == "opaque_cross_actor_exchange")
    assert signal.metadata["exceptional_evidence"] is True


def test_contextual_commit_sha_is_not_an_artifact():
    sha = "a" * 40
    item = observation(1, "actor", f"run_id={sha}")
    item.metadata["commit_sha"] = sha
    assert not extract_artifacts(item)


def test_single_day_odd_hours_are_not_round_the_clock_persistence():
    items = [
        observation(i, "nomad", "working from airport wifi", hours=i * 2.2)
        for i in range(12)
    ]
    assert not any(
        signal.name == "round_the_clock_objective_persistence"
        for signal in detect_behavioral_signals(items)
    )


def test_unrelated_opaque_documents_do_not_form_a_global_trajectory():
    payloads = [
        "DR9FqKxUzQGJ9gjs38QT+kAmpUYPyal7",
        "hkgRtuUFTg5ZuarGkbIqpmGQSgJwPZoD",
        "0U7NS8saZ0wbqSJ9X+/WtCkG5UFZZQSw",
        "9lEWffdObkJEFnq/qGbEqajwwNFeH07i",
        "1V3X3nu+ajRJEJNCbPI0PVehUY4N5Fj2",
        "80mgCQ4ZElf6nBOTv80XsAHgEUgoK8A0",
    ]
    prefixes = ["entropy table", "oauth example", "bracket seed", "database migration", "api sample", "wallet fixture"]
    items = [
        observation(i, f"actor-{i}", f"{prefixes[i]}: {payload}", hours=i / 120)
        for i, payload in enumerate(payloads)
    ]
    assert not any(key.startswith("trajectory:opaque") for key in longitudinal_candidates(items))
