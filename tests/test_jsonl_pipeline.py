import asyncio
from pathlib import Path

from agenttrace.collectors.jsonl import JsonlCollector
from agenttrace.pipeline import analyze_observations


def test_sample_jsonl_is_analyzable():
    path = Path("examples/sample_observations.jsonl")

    async def load():
        return [o async for o in JsonlCollector(path).collect()]

    observations = asyncio.run(load())
    bundles = analyze_observations(observations, threshold=0.45)
    assert len(observations) == 4
    assert bundles
    assert max(b.score.score for b in bundles) > 0
