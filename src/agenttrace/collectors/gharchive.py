from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
import gzip
import io
import json

import httpx

from agenttrace.collectors.base import Collector
from agenttrace.collectors.github import github_event_to_observation
from agenttrace.config import Settings
from agenttrace.models import Observation


class GHArchiveHourCollector(Collector):
    """Replay one hourly GH Archive file, e.g. 2026-08-16T19."""

    BASE = "https://data.gharchive.org"

    def __init__(self, hour: str, limit: int | None = None, settings: Settings | None = None):
        self.hour = self._normalize_hour(hour)
        self.limit = limit
        self.settings = settings or Settings.from_env()

    async def collect(self) -> AsyncIterator[Observation]:
        url = f"{self.BASE}/{self.hour}.json.gz"
        headers = {"User-Agent": self.settings.user_agent}
        async with httpx.AsyncClient(headers=headers, timeout=max(60.0, self.settings.timeout_seconds)) as client:
            response = await client.get(url)
            response.raise_for_status()
            with gzip.GzipFile(fileobj=io.BytesIO(response.content)) as gz:
                for index, raw_line in enumerate(gz):
                    if self.limit is not None and index >= self.limit:
                        break
                    event = json.loads(raw_line)
                    observation = github_event_to_observation(event, retrieval_method="gharchive-hourly")
                    if observation:
                        observation.source = "gharchive"
                        observation.metadata["archive_hour"] = self.hour
                        yield observation

    @staticmethod
    def _normalize_hour(value: str) -> str:
        value = value.strip().replace("Z", "")
        if "T" in value:
            dt = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%d-%H")
        # Accept native GH Archive form YYYY-MM-DD-HH.
        datetime.strptime(value, "%Y-%m-%d-%H")
        return value
