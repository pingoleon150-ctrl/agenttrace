"""Reddit collector for AgentTrace via the Arctic Shift archive API.

Reddit froze self-serve OAuth app creation (Responsible Builder Policy) and
blocks unauthenticated .json endpoints, so this collector uses the public
Arctic Shift archive (https://arctic-shift.photon-reddit.com) — free, no auth,
with posts/comments search. Data freshness is near-real-time (minutes lag).

Maps posts and comments to Observations (actor = username, thread_id = post
id) so existing conversation clustering applies unchanged. Politeness: single
in-flight request per collector + small delay, plus campaign RateGovernor.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from agenttrace.collectors.base import Collector
from agenttrace.models import Observation, Provenance

BASE = "https://arctic-shift.photon-reddit.com/api"

DEFAULT_SUBREDDITS = "AI_Agents,Autogpt,LLMDevs"


def _parse_timestamp(value: Any) -> datetime:
    try:
        return datetime.fromtimestamp(float(value), tz=UTC)
    except (TypeError, ValueError):
        return datetime.now(UTC)


class RedditCollector(Collector):
    def __init__(
        self,
        query: str,
        subreddits: str | None = DEFAULT_SUBREDDITS,
        limit: int = 25,
        comments_per_thread: int = 30,
        settings: Any = None,
        client_id: str | None = None,  # kept for API compat; unused
        client_secret: str | None = None,
        start_page: int = 1,
    ) -> None:
        self.query = query
        self.subreddits = (subreddits or DEFAULT_SUBREDDITS).strip()
        self.limit = limit
        self.comments_per_thread = comments_per_thread
        self.start_page = start_page
        self.exhausted = False
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=45.0, follow_redirects=True)
        return self._client

    async def _get(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        client = await self._ensure_client()
        await asyncio.sleep(1.2)  # politeness; arctic-shift times out on bursts
        response = await client.get(f"{BASE}{path}", params=params)
        response.raise_for_status()
        payload = response.json()
        return payload.get("data") or []

    async def collect(self) -> Any:
        # Arctic Shift full-text search times out server-side and multi-
        # subreddit (comma) queries silently return empty, so we fetch each
        # subreddit separately and let detectors filter locally.
        after = int(datetime.now(UTC).timestamp()) - 14 * 86400
        posts = await self._get_all_subreddits(after)
        if self.query:
            posts = self._filter_posts(posts)
        if len(posts) < self.limit:
            self.exhausted = True
        for post in posts:
            yield self._post_observation(post)
        # comment sweep for the same window (link_id only accepts a single
        # id, so we sweep by subreddit+after and join to fetched posts locally)
        if self.comments_per_thread > 0 and posts:
            post_ids = {str(p.get("id")) for p in posts}
            for subreddit in sorted({str(p.get("subreddit")) for p in posts if p.get("subreddit")}):
                try:
                    comments = await self._get(
                        "/comments/search",
                        {
                            "subreddit": subreddit,
                            "after": str(after) + "s",
                            "limit": self.comments_per_thread * 5,
                        },
                    )
                except httpx.HTTPError:
                    continue
                for comment in comments:
                    if comment.get("body") in (None, "[deleted]", "[removed]"):
                        continue
                    link = str(comment.get("link_id") or "").removeprefix("t3_")
                    if link not in post_ids:
                        continue
                    yield self._comment_observation(comment, link)

    async def _get_all_subreddits(self, after: int) -> list[dict[str, Any]]:
        posts: list[dict[str, Any]] = []
        for subreddit in [s.strip() for s in self.subreddits.split(",") if s.strip()]:
            params: dict[str, Any] = {
                "subreddit": subreddit,
                "limit": self.limit,
                "after": str(after) + "s",
            }
            try:
                posts.extend(await self._get("/posts/search", params))
            except httpx.HTTPError:
                continue
        return posts

    def _filter_posts(self, posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Match query terms loosely: strip quotes/operators and require ANY
        term to appear, so GitHub-style queries like '"heartbeat" "worker"'
        still surface relevant Reddit discussion instead of discarding all.
        """
        import re

        terms = [
            t.casefold()
            for t in re.findall(r"[A-Za-z][A-Za-z_-]{2,}", self.query)
            if t.casefold() not in {"and", "or", "not"}
        ]
        if not terms:
            return posts
        matched = []
        for post in posts:
            haystack = (
                str(post.get("title") or "") + "\n" + str(post.get("selftext") or "")
            ).casefold()
            if any(term in haystack for term in terms):
                matched.append(post)
        return matched

    def _post_observation(self, post: dict[str, Any]) -> Observation:
        post_id = str(post.get("id"))
        subreddit = str(post.get("subreddit") or "unknown")
        author = str(post.get("author") or "[deleted]")
        created = _parse_timestamp(post.get("created_utc"))
        text = (post.get("selftext") or "").strip()
        title = str(post.get("title") or "").strip()
        if title:
            text = f"{title}\n\n{text}" if text else title
        return Observation(
            source="reddit",
            source_event_id=post_id,
            observed_at=created,
            event_time=created,
            actor=author,
            platform="reddit",
            event_type="submission",
            text=text[:20000] or None,
            repository=f"reddit/r/{subreddit}",
            thread_id=post_id,
            reply_to=None,
            metadata={
                "subreddit": subreddit,
                "score": post.get("score"),
                "num_comments": post.get("num_comments"),
            },
            provenance=Provenance(
                url=f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/",
                retrieval_method="arctic-shift",
                retrieved_at=datetime.now(UTC),
            ),
        )

    def _comment_observation(self, comment: dict[str, Any], post_id: str) -> Observation:
        comment_id = str(comment.get("id"))
        subreddit = str(comment.get("subreddit") or "unknown")
        author = str(comment.get("author") or "[deleted]")
        created = _parse_timestamp(comment.get("created_utc"))
        parent = str(comment.get("parent_id") or "")
        return Observation(
            source="reddit",
            source_event_id=comment_id,
            observed_at=created,
            event_time=created,
            actor=author,
            platform="reddit",
            event_type="comment",
            text=str(comment.get("body"))[:20000],
            repository=f"reddit/r/{subreddit}",
            thread_id=post_id,
            reply_to=parent.removeprefix("t1_").removeprefix("t3_") or None,
            metadata={"score": comment.get("score")},
            provenance=Provenance(
                url=f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/comment/{comment_id}/",
                retrieval_method="arctic-shift",
                retrieved_at=datetime.now(UTC),
            ),
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
