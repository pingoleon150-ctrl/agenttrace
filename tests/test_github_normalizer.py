from agenttrace.collectors.github import github_event_to_observation


def test_issue_comment_event_normalizes():
    event = {
        "id": "123",
        "type": "IssueCommentEvent",
        "created_at": "2026-08-16T19:00:00Z",
        "actor": {"login": "worker-a"},
        "repo": {"name": "org/repo"},
        "public": True,
        "payload": {
            "action": "created",
            "issue": {
                "id": 9,
                "number": 7,
                "title": "task",
                "body": "TASK-ID: abc-1234",
                "html_url": "https://github.com/org/repo/issues/7",
            },
            "comment": {
                "id": 10,
                "body": "ACK",
                "html_url": "https://github.com/org/repo/issues/7#issuecomment-10",
            },
        },
    }
    obs = github_event_to_observation(event, "test")
    assert obs.repository == "org/repo"
    assert obs.thread_id == "7"
    assert "ACK" in (obs.text or "")
    assert "abc-1234" not in (obs.text or "")
    assert obs.reply_to is None
    assert obs.metadata["conversation_root"] == "issue:9"


def test_push_event_retains_commit_features_without_email_local_part():
    event = {
        "id": "124",
        "type": "PushEvent",
        "created_at": "2026-08-16T19:00:00Z",
        "actor": {"login": "worker-a"},
        "repo": {"name": "org/repo"},
        "payload": {
            "commits": [
                {
                    "sha": "a" * 40,
                    "message": "Update shard 12",
                    "url": "https://github.com/org/repo/commit/" + "a" * 40,
                    "author": {"email": "private-name@users.noreply.github.com"},
                }
            ]
        },
    }
    obs = github_event_to_observation(event, "test")
    assert obs.metadata["commit_messages"] == ["Update shard 12"]
    assert obs.metadata["author_email_domains"] == ["users.noreply.github.com"]
    assert "private-name" not in obs.model_dump_json()
