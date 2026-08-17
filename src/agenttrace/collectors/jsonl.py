from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from agenttrace.collectors.base import Collector
from agenttrace.models import Observation


class JsonlCollector(Collector):
    def __init__(self, path: str | Path):
        self.path = Path(path)

    async def collect(self) -> AsyncIterator[Observation]:
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    yield Observation.model_validate_json(line)
