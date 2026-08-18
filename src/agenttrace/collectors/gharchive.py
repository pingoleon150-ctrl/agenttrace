from __future__ import annotations

import hashlib
import json
import re
import zlib
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import httpx

from agenttrace.collectors.base import Collector
from agenttrace.collectors.github import github_event_to_observation
from agenttrace.config import Settings
from agenttrace.models import Observation

DEFAULT_EVENT_TYPES = {
    "IssuesEvent",
    "IssueCommentEvent",
    "PullRequestEvent",
    "PushEvent",
    "CreateEvent",
}
CANDIDATE_RE = re.compile(
    rb"(?:task[_ -]?id|worker[_ -]?id|resume[_ -]?token|continuation[_ -]?token|"
    rb"checkpoint|nonce|delegate|coordinator|heartbeat)",
    re.IGNORECASE,
)
EVENT_TYPE_RE = re.compile(rb'"type"\s*:\s*"(?P<value>[A-Za-z]+Event)"')
EVENT_ID_RE = re.compile(rb'"id"\s*:\s*"(?P<value>[^"]+)"')
REPOSITORY_RE = re.compile(rb'"repo"\s*:\s*\{[^{}]*"name"\s*:\s*"(?P<value>[^"]+)"')
INFLATE_CHUNK_BYTES = 64 * 1024
MAX_ARCHIVE_CODE_BLOCKS = 4
MAX_ARCHIVE_CODE_CHARS = 4_096
MAX_ARCHIVE_URLS = 20
MAX_ARCHIVE_URL_CHARS = 2_048


class GHArchiveHourCollector(Collector):
    """Stream and deterministically sample one bounded GH Archive hour."""

    BASE = "https://data.gharchive.org"

    def __init__(
        self,
        hour: str,
        limit: int | None = None,
        settings: Settings | None = None,
        *,
        sample_rate: float = 0.05,
        event_types: set[str] | None = None,
        max_observations: int = 10_000,
        max_download_bytes: int = 512 * 1024 * 1024,
        max_text_chars: int = 20_000,
        max_event_bytes: int = 2 * 1024 * 1024,
        transport: httpx.AsyncBaseTransport | None = None,
        repositories: set[str] | None = None,
    ):
        self.hour = self._normalize_hour(hour)
        self.limit = limit
        self.settings = settings or Settings.from_env()
        self.sample_rate = max(0.0, min(1.0, sample_rate))
        self.event_types = event_types or DEFAULT_EVENT_TYPES
        self.max_observations = max(1, max_observations)
        self.background_budget = self.max_observations // 5
        self.candidate_budget = self.max_observations - self.background_budget
        self.max_download_bytes = max(1, max_download_bytes)
        self.max_text_chars = max(100, max_text_chars)
        self.max_event_bytes = max(1024, max_event_bytes)
        self.transport = transport
        self.repositories = {value.casefold() for value in repositories or set()}
        self.stats = {
            "events_scanned": 0,
            "relevant_events": 0,
            "candidate_events": 0,
            "sampled_events": 0,
            "candidate_observations": 0,
            "sampled_observations": 0,
            "dropped_candidate_events": 0,
            "dropped_sampled_events": 0,
            "observations": 0,
            "compressed_bytes": 0,
            "malformed_events": 0,
            "repository_filtered_events": 0,
        }

    async def collect(self) -> AsyncIterator[Observation]:
        url = f"{self.BASE}/{self.hour}.json.gz"
        headers = {"User-Agent": self.settings.user_agent}
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        pending = bytearray()
        async with httpx.AsyncClient(
            headers=headers,
            timeout=max(60.0, self.settings.timeout_seconds),
            transport=self.transport,
        ) as client, client.stream("GET", url) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                self.stats["compressed_bytes"] += len(chunk)
                if self.stats["compressed_bytes"] > self.max_download_bytes:
                    raise RuntimeError("GH Archive compressed download exceeded configured limit")
                for raw_line in self._inflate_lines(decompressor, pending, chunk):
                    if len(raw_line) > self.max_event_bytes:
                        self.stats["malformed_events"] += 1
                        continue
                    observation = self._process_line(raw_line)
                    if observation:
                        yield observation
                    if self._finished():
                        return
            if not decompressor.eof:
                raise RuntimeError("GH Archive gzip stream ended before its checksum trailer")
            pending.extend(decompressor.flush())
        if len(pending) > self.max_event_bytes:
            raise RuntimeError("GH Archive event exceeded configured line limit")
        if bytes(pending).strip() and not self._finished():
            observation = self._process_line(bytes(pending))
            if observation:
                yield observation

    def _process_line(self, raw_line: bytes) -> Observation | None:
        if not raw_line:
            return None
        self.stats["events_scanned"] += 1
        if self.limit is not None and self.stats["events_scanned"] > self.limit:
            return None
        event_type_match = EVENT_TYPE_RE.search(raw_line)
        event_type = event_type_match.group("value").decode() if event_type_match else None
        if event_type and event_type not in self.event_types:
            return None
        if self.repositories:
            repository_match = REPOSITORY_RE.search(raw_line)
            repository = (
                repository_match.group("value").decode(errors="replace").casefold()
                if repository_match
                else ""
            )
            if repository not in self.repositories:
                self.stats["repository_filtered_events"] += 1
                return None
        self.stats["relevant_events"] += 1
        event_id_match = EVENT_ID_RE.search(raw_line)
        event_id = event_id_match.group("value").decode() if event_id_match else ""
        raw_candidate = bool(CANDIDATE_RE.search(raw_line))
        sampled = self._sampled(event_id)
        if not raw_candidate and not sampled:
            return None
        try:
            event = json.loads(raw_line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.stats["malformed_events"] += 1
            return None
        if event.get("type") not in self.event_types:
            return None
        observation = github_event_to_observation(event, retrieval_method="gharchive-hourly")
        if not observation:
            return None
        candidate = bool(CANDIDATE_RE.search((observation.text or "").encode()))
        if not candidate and not sampled:
            return None
        if candidate:
            self.stats["candidate_events"] += 1
            if self.stats["candidate_observations"] >= self.candidate_budget:
                self.stats["dropped_candidate_events"] += 1
                return None
            self.stats["candidate_observations"] += 1
        else:
            self.stats["sampled_events"] += 1
            if self.stats["sampled_observations"] >= self.background_budget:
                self.stats["dropped_sampled_events"] += 1
                return None
            self.stats["sampled_observations"] += 1
        observation = observation.model_copy(
            update={
                "source": "gharchive",
                "event_key": f"github:event:gharchive:{observation.source_event_id}",
                "parent_key": None,
            }
        )
        observation.metadata["archive_hour"] = self.hour
        observation.metadata["candidate_retained"] = candidate
        if observation.text and len(observation.text) > self.max_text_chars:
            observation.text = observation.text[: self.max_text_chars]
            observation.metadata["text_truncated"] = True
        observation.code_blocks = [
            block[:MAX_ARCHIVE_CODE_CHARS]
            for block in observation.code_blocks[:MAX_ARCHIVE_CODE_BLOCKS]
        ]
        observation.artifact_urls = [
            url[:MAX_ARCHIVE_URL_CHARS]
            for url in observation.artifact_urls[:MAX_ARCHIVE_URLS]
        ]
        self.stats["observations"] += 1
        return observation

    def _inflate_lines(
        self,
        decompressor: zlib.Decompress,
        pending: bytearray,
        compressed: bytes,
    ) -> Iterator[bytes]:
        remaining = compressed
        while remaining:
            output = decompressor.decompress(remaining, INFLATE_CHUNK_BYTES)
            remaining = decompressor.unconsumed_tail
            pending.extend(output)
            while True:
                newline = pending.find(b"\n")
                if newline < 0:
                    break
                raw_line = bytes(pending[:newline])
                del pending[: newline + 1]
                yield raw_line
            if len(pending) > self.max_event_bytes:
                raise RuntimeError("GH Archive event exceeded configured line limit")

    def _sampled(self, event_id: str) -> bool:
        if self.sample_rate <= 0.0:
            return False
        digest = hashlib.sha256(event_id.encode()).digest()
        value = int.from_bytes(digest[:8], "big") / 2**64
        return value < self.sample_rate

    def _finished(self) -> bool:
        return self.limit is not None and self.stats["events_scanned"] >= self.limit

    @staticmethod
    def _normalize_hour(value: str) -> str:
        value = value.strip().replace("Z", "")
        if "T" in value:
            dt = datetime.fromisoformat(value).replace(tzinfo=UTC)
        else:
            dt = datetime.strptime(value, "%Y-%m-%d-%H").replace(tzinfo=UTC)
        # GH Archive names hours 0-9 without a leading zero.
        return f"{dt:%Y-%m-%d}-{dt.hour}"
