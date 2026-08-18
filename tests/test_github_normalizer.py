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
