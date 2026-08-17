from __future__ import annotations

import re
from collections.abc import AsyncIterator
from html import unescape

import httpx

from agenttrace.collectors.base import Collector
from agenttrace.config import Settings
from agenttrace.models import Observation, Provenance
from agenttrace.util import sha256_text, utcnow

TAG_RE = re.compile(r"<[^>]+>")


class GrepAppCollector(Collector):
    """Experimental adapter for grep.app's public code-search endpoint.

    This is intentionally isolated behind an adapter because third-party APIs can change
    without notice. Do not treat this source as authoritative provenance by itself.
    """

    API = "https://grep.app/api/search"

    def __init__(
        self,
        query: str,
        limit: int = 100,
        settings: Settings | None = None,
        start_page: int = 1,
    ):
        self.query = query
        self.limit = max(1, min(limit, 1000))
        self.settings = settings or Settings.from_env()
        self.start_page = max(1, start_page)
        self.exhausted = False

    async def collect(self) -> AsyncIterator[Observation]:
        fetched = 0
        page = self.start_page
        headers = {"User-Agent": self.settings.user_agent}
        async with httpx.AsyncClient(
            headers=headers, timeout=self.settings.timeout_seconds
        ) as client:
            while fetched < self.limit:
                response = await client.get(self.API, params={"q": self.query, "page": page})
                response.raise_for_status()
                hits = (response.json().get("hits") or {}).get("hits") or []
                if not hits:
                    self.exhausted = True
                    break
                for hit in hits:
                    repo = _raw(hit.get("repo"))
                    path = _raw(hit.get("path"))
                    content = _clean_snippet((hit.get("content") or {}).get("snippet", ""))
                    text = f"{repo}:{path}\n{content}".strip()
                    url = (
                        f"https://github.com/{repo}/blob/HEAD/{path}"
                        if repo and path
                        else "https://grep.app"
                    )
                    yield Observation(
                        source="grep.app",
                        source_event_id=f"grep:{sha256_text(text)}",
                        observed_at=utcnow(),
                        event_time=utcnow(),
                        actor=repo.split("/", 1)[0] if "/" in repo else repo or "unknown",
                        event_type="code_search_hit",
                        text=text,
                        repository=repo or None,
                        artifact_urls=[],
                        code_blocks=[content] if content else [],
                        content_sha256=sha256_text(text),
                        metadata={"path": path, "query": self.query, "experimental": True},
                        provenance=Provenance(
                            url=url,
                            retrieval_method="grep.app-public-search",
                            retrieved_at=utcnow(),
                        ),
                    )
                    fetched += 1
                    if fetched >= self.limit:
                        break
                page += 1


def _raw(value) -> str:
    if isinstance(value, dict):
        return str(value.get("raw") or value.get("name") or "")
    return str(value or "")


def _clean_snippet(value: str) -> str:
    return unescape(TAG_RE.sub("", value)).strip()
