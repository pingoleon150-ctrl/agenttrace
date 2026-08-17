from agenttrace.collectors.github import github_event_to_observation


def test_provenance_url_is_not_an_artifact():
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
                "body": "plain text",
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
    assert obs.provenance.url.startswith("https://github.com/")
    assert obs.artifact_urls == []
