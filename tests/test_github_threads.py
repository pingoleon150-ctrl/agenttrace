import asyncio

from agenttrace.collectors.github import GitHubThreadSearchCollector
from agenttrace.pipeline import analyze_cluster


class Response:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeGitHubClient:
    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, path, params=None):
        if path == "/search/issues":
            return Response(
                {
                    "items": [
                        {
                            "id": 10,
                            "number": 7,
                            "title": "Example",
                            "body": "Root body",
                            "created_at": "2026-08-17T12:00:00+00:00",
                            "repository_url": "https://api.github.com/repos/example/repo",
                            "html_url": "https://github.com/example/repo/issues/7",
                            "state": "open",
                            "user": {"login": "alice", "type": "User"},
                        }
                    ]
                }
            )
        return Response(
            [
                {
                    "id": 11,
                    "body": "First comment",
                    "created_at": "2026-08-17T12:01:00+00:00",
                    "html_url": "https://github.com/example/repo/issues/7#issuecomment-11",
                    "user": {"login": "bob", "type": "User"},
                },
                {
                    "id": 12,
                    "body": "Second comment",
                    "created_at": "2026-08-17T12:02:00+00:00",
                    "html_url": "https://github.com/example/repo/issues/7#issuecomment-12",
                    "user": {"login": "carol", "type": "User"},
                },
            ]
        )


class FakeGitHubPRClient(FakeGitHubClient):
    async def get(self, path, params=None):
        if path == "/search/issues":
            response = await super().get(path, params)
            response.payload["items"][0]["pull_request"] = {
                "url": "https://api.github.com/repos/example/repo/pulls/7"
            }
            return response
        if path.endswith("/issues/7/comments"):
            return Response([])
        return Response(
            [
                {
                    "id": 21,
                    "body": "Please run this check",
                    "created_at": "2026-08-17T12:01:00+00:00",
                    "html_url": "https://github.com/example/repo/pull/7#discussion_r21",
                    "user": {"login": "coordinator", "type": "User"},
                },
                {
                    "id": 22,
                    "in_reply_to_id": 21,
                    "body": "ACK",
                    "created_at": "2026-08-17T12:02:00+00:00",
                    "html_url": "https://github.com/example/repo/pull/7#discussion_r22",
                    "user": {"login": "worker", "type": "User"},
                },
                {
                    "id": 23,
                    "in_reply_to_id": 22,
                    "body": "Task completed; reporting back",
                    "created_at": "2026-08-17T12:03:00+00:00",
                    "html_url": "https://github.com/example/repo/pull/7#discussion_r23",
                    "user": {"login": "worker", "type": "User"},
                },
            ]
        )


def test_sequential_issue_comments_are_not_invented_as_replies(monkeypatch):
    monkeypatch.setattr("agenttrace.collectors.github.GitHubClient", FakeGitHubClient)
    collector = GitHubThreadSearchCollector("query", threads=1, comments_per_thread=2)

    observations = asyncio.run(_collect(collector))
    comments = [obs for obs in observations if obs.event_type == "issue_comment"]

    assert len(comments) == 2
    assert all(comment.reply_to is None for comment in comments)
    assert all(comment.parent_key is None for comment in comments)
    assert {comment.metadata["conversation_root"] for comment in comments} == {"issue:10"}


def test_pr_review_comments_preserve_native_reply_ids(monkeypatch):
    monkeypatch.setattr("agenttrace.collectors.github.GitHubClient", FakeGitHubPRClient)
    collector = GitHubThreadSearchCollector("query", threads=1, comments_per_thread=3)

    observations = asyncio.run(_collect(collector))
    comments = [
        obs for obs in observations if obs.event_type == "pull_request_review_comment"
    ]

    assert len(comments) == 3
    assert comments[0].parent_key is None
    assert comments[1].reply_to == "review-comment:21"
    assert comments[1].parent_key == comments[0].event_key
    assert comments[2].parent_key == comments[1].event_key

    bundle = analyze_cluster("native-pr-review", comments, threshold=0.75)
    assert bundle.score.reviewable is True
    assert "route=verified_relational_exchange" in bundle.score.reasons


async def _collect(collector):
    return [observation async for observation in collector.collect()]
