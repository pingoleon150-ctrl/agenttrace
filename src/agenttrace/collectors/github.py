from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any, Self

import httpx

from agenttrace.collectors.base import Collector
from agenttrace.config import Settings
from agenttrace.models import Observation, Provenance
from agenttrace.util import extract_code_blocks, extract_urls, sha256_text, utcnow


class GitHubClient:
    BASE = "https://api.github.com"

    def __init__(
        self, settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None
    ):
        self.settings = settings or Settings.from_env()
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": self.settings.user_agent,
        }
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token}"
        self.client = httpx.AsyncClient(
            base_url=self.BASE,
            headers=headers,
            timeout=self.settings.timeout_seconds,
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.client.aclose()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        response = await self.client.get(path, params=params)
        if response.status_code == 403 and "rate limit" in response.text.lower():
            reset = response.headers.get("x-ratelimit-reset", "unknown")
            raise RuntimeError(f"GitHub rate limit reached; reset={reset}")
        response.raise_for_status()
        return response


class GitHubIssueSearchCollector(Collector):
    def __init__(self, query: str, limit: int = 100, settings: Settings | None = None):
        self.query = query
        self.limit = max(1, min(limit, 1000))
        self.settings = settings or Settings.from_env()

    async def collect(self) -> AsyncIterator[Observation]:
        fetched = 0
        page = 1
        async with GitHubClient(self.settings) as gh:
            while fetched < self.limit:
                per_page = min(100, self.limit - fetched)
                response = await gh.get(
                    "/search/issues",
                    params={"q": self.query, "per_page": per_page, "page": page},
                )
                items = response.json().get("items", [])
                if not items:
                    break
                for item in items:
                    fetched += 1
                    text = "\n\n".join(filter(None, [item.get("title"), item.get("body")]))
                    repo_url = item.get("repository_url", "")
                    repository = repo_url.split("/repos/", 1)[-1] if "/repos/" in repo_url else None
                    event_time = _parse_dt(item.get("updated_at") or item.get("created_at"))
                    yield Observation(
                        source="github-search",
                        source_event_id=f"issue:{item['id']}",
                        observed_at=utcnow(),
                        event_time=event_time,
                        actor=(item.get("user") or {}).get("login", "unknown"),
                        event_type="pull_request" if "pull_request" in item else "issue",
                        text=text,
                        repository=repository,
                        thread_id=str(item.get("number")),
                        artifact_urls=extract_urls(text),
                        code_blocks=extract_code_blocks(text),
                        content_sha256=sha256_text(text),
                        metadata={
                            "number": item.get("number"),
                            "state": item.get("state"),
                            "labels": [label.get("name") for label in item.get("labels", [])],
                            "comments": item.get("comments", 0),
                        },
                        provenance=Provenance(
                            url=item.get("html_url", ""),
                            retrieval_method="github-rest-search-issues",
                            retrieved_at=utcnow(),
                        ),
                    )
                    if fetched >= self.limit:
                        break
                page += 1


class GitHubThreadSearchCollector(Collector):
    """Search candidate issues/PRs and expand each result into its public conversation thread."""

    def __init__(
        self,
        query: str,
        threads: int = 20,
        comments_per_thread: int = 100,
        settings: Settings | None = None,
        repository_allowed: Callable[[str], bool] | None = None,
    ):
        self.query = query
        self.threads = max(1, min(threads, 100))
        self.comments_per_thread = max(1, min(comments_per_thread, 500))
        self.settings = settings or Settings.from_env()
        self.repository_allowed = repository_allowed

    async def collect(self) -> AsyncIterator[Observation]:
        async with GitHubClient(self.settings) as gh:
            response = await gh.get(
                "/search/issues",
                params={"q": self.query, "per_page": self.threads, "page": 1},
            )
            for item in response.json().get("items", [])[: self.threads]:
                repo_url = item.get("repository_url", "")
                repository = repo_url.split("/repos/", 1)[-1] if "/repos/" in repo_url else None
                if not repository:
                    continue
                if self.repository_allowed and not self.repository_allowed(repository):
                    continue
                number = item.get("number")
                root_text = "\n\n".join(filter(None, [item.get("title"), item.get("body")]))
                root_id = f"issue:{item['id']}"
                yield Observation(
                    source="github-thread-search",
                    source_event_id=root_id,
                    observed_at=utcnow(),
                    event_time=_parse_dt(item.get("created_at")),
                    actor=(item.get("user") or {}).get("login", "unknown"),
                    event_type="pull_request" if "pull_request" in item else "issue",
                    text=root_text,
                    repository=repository,
                    thread_id=str(number),
                    artifact_urls=extract_urls(root_text),
                    code_blocks=extract_code_blocks(root_text),
                    content_sha256=sha256_text(root_text),
                    metadata={"number": number, "state": item.get("state"), "root": True},
                    provenance=Provenance(
                        url=item.get("html_url", ""),
                        retrieval_method="github-rest-thread-search",
                        retrieved_at=utcnow(),
                    ),
                )

                fetched = 0
                page = 1
                previous_id = root_id
                while fetched < self.comments_per_thread:
                    per_page = min(100, self.comments_per_thread - fetched)
                    comments_response = await gh.get(
                        f"/repos/{repository}/issues/{number}/comments",
                        params={"per_page": per_page, "page": page},
                    )
                    comments = comments_response.json()
                    if not comments:
                        break
                    for comment in comments:
                        comment_text = comment.get("body") or ""
                        comment_id = f"comment:{comment['id']}"
                        yield Observation(
                            source="github-thread-search",
                            source_event_id=comment_id,
                            observed_at=utcnow(),
                            event_time=_parse_dt(comment.get("created_at")),
                            actor=(comment.get("user") or {}).get("login", "unknown"),
                            event_type="issue_comment",
                            text=comment_text,
                            repository=repository,
                            thread_id=str(number),
                            reply_to=previous_id,
                            artifact_urls=extract_urls(comment_text),
                            code_blocks=extract_code_blocks(comment_text),
                            content_sha256=sha256_text(comment_text),
                            metadata={"issue_number": number, "root": False},
                            provenance=Provenance(
                                url=comment.get("html_url", item.get("html_url", "")),
                                retrieval_method="github-rest-thread-comments",
                                retrieved_at=utcnow(),
                            ),
                        )
                        previous_id = comment_id
                        fetched += 1
                        if fetched >= self.comments_per_thread:
                            break
                    page += 1


class GitHubCodeSearchCollector(Collector):
    def __init__(self, query: str, limit: int = 100, settings: Settings | None = None):
        self.query = query
        self.limit = max(1, min(limit, 1000))
        self.settings = settings or Settings.from_env()
        if not self.settings.github_token:
            raise ValueError("GitHub code search requires GITHUB_TOKEN or GH_TOKEN")

    async def collect(self) -> AsyncIterator[Observation]:
        fetched = 0
        page = 1
        async with GitHubClient(self.settings) as gh:
            while fetched < self.limit:
                per_page = min(100, self.limit - fetched)
                response = await gh.get(
                    "/search/code",
                    params={"q": self.query, "per_page": per_page, "page": page},
                )
                items = response.json().get("items", [])
                if not items:
                    break
                for item in items:
                    fetched += 1
                    repo = (item.get("repository") or {}).get("full_name")
                    path = item.get("path", "")
                    text = f"{repo}:{path}"
                    yield Observation(
                        source="github-code-search",
                        source_event_id=f"code:{item.get('sha')}:{path}",
                        observed_at=utcnow(),
                        event_time=utcnow(),
                        actor=(item.get("repository") or {})
                        .get("owner", {})
                        .get("login", "unknown"),
                        event_type="code_search_hit",
                        text=text,
                        repository=repo,
                        artifact_urls=[],
                        content_sha256=sha256_text(text),
                        metadata={"path": path, "sha": item.get("sha"), "score": item.get("score")},
                        provenance=Provenance(
                            url=item.get("html_url", ""),
                            retrieval_method="github-rest-search-code",
                            retrieved_at=utcnow(),
                        ),
                    )
                    if fetched >= self.limit:
                        break
                page += 1


class GitHubPublicEventsCollector(Collector):
    def __init__(self, pages: int = 1, settings: Settings | None = None):
        self.pages = max(1, min(pages, 10))
        self.settings = settings or Settings.from_env()

    async def collect(self) -> AsyncIterator[Observation]:
        async with GitHubClient(self.settings) as gh:
            for page in range(1, self.pages + 1):
                response = await gh.get("/events", params={"per_page": 100, "page": page})
                events = response.json()
                if not events:
                    break
                for event in events:
                    obs = github_event_to_observation(
                        event, retrieval_method="github-public-events"
                    )
                    if obs:
                        yield obs


def github_event_to_observation(event: dict[str, Any], retrieval_method: str) -> Observation | None:
    event_type = event.get("type", "unknown")
    payload = event.get("payload") or {}
    actor = (event.get("actor") or {}).get("login", "unknown")
    repository = (event.get("repo") or {}).get("name")
    created_at = _parse_dt(event.get("created_at"))

    text_parts: list[str] = []
    urls: list[str] = []
    thread_id: str | None = None
    reply_to: str | None = None

    if event_type in {"IssuesEvent", "IssueCommentEvent"}:
        issue = payload.get("issue") or {}
        comment = payload.get("comment") or {}
        text_parts.extend(
            filter(None, [issue.get("title"), issue.get("body"), comment.get("body")])
        )
        thread_id = str(issue.get("number")) if issue.get("number") is not None else None
        urls.extend(filter(None, [issue.get("html_url"), comment.get("html_url")]))
        if comment.get("id"):
            reply_to = f"issue:{issue.get('id')}"
    elif event_type == "PullRequestEvent":
        pr = payload.get("pull_request") or {}
        text_parts.extend(filter(None, [pr.get("title"), pr.get("body")]))
        thread_id = str(pr.get("number")) if pr.get("number") is not None else None
        urls.extend(filter(None, [pr.get("html_url")]))
    elif event_type == "PushEvent":
        for commit in payload.get("commits") or []:
            if commit.get("message"):
                text_parts.append(commit["message"])
            if commit.get("url"):
                urls.append(commit["url"])
    elif event_type == "CreateEvent":
        text_parts.extend(
            filter(None, [payload.get("ref_type"), payload.get("ref"), payload.get("description")])
        )
    else:
        # Keep metadata-only events useful for temporal analysis without pretending they contain text.
        text_parts.append(event_type)

    text = "\n".join(text_parts).strip() or None
    public_url = (
        urls[0]
        if urls
        else (f"https://github.com/{repository}" if repository else "https://github.com")
    )
    return Observation(
        source="github-events",
        source_event_id=str(event.get("id")),
        observed_at=utcnow(),
        event_time=created_at,
        actor=actor,
        event_type=event_type,
        text=text,
        repository=repository,
        thread_id=thread_id,
        reply_to=reply_to,
        artifact_urls=extract_urls(text),
        code_blocks=extract_code_blocks(text),
        content_sha256=sha256_text(text or event_type),
        metadata={"public": event.get("public", True), "payload_action": payload.get("action")},
        provenance=Provenance(
            url=public_url, retrieval_method=retrieval_method, retrieved_at=utcnow()
        ),
    )


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    return datetime.fromisoformat(value)
