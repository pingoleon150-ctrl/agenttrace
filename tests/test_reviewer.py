import json

from agenttrace.reviewer import redact_public_text, reviewer_from_openclaw


def test_openclaw_loader_reads_provider_without_copying_secret(tmp_path):
    config = tmp_path / "openclaw.json"
    config.write_text(
        json.dumps(
            {
                "models": {
                    "providers": {
                        "example": {
                            "baseUrl": "https://example.test/v1",
                            "apiKey": "private-value",
                            "models": [{"id": "model-a"}],
                        }
                    }
                }
            }
        )
    )
    reviewer = reviewer_from_openclaw(config, "example")
    assert reviewer.model_name == "model-a"
    assert reviewer.base_url == "https://example.test/v1"
    assert "private-value" not in repr(reviewer)


def test_public_text_redacts_common_credentials():
    text = "api_key=secret-value password: hunter2 token is not a credential label"
    redacted = redact_public_text(text)
    assert "secret-value" not in redacted
    assert "hunter2" not in redacted


def test_openclaw_gateway_uses_private_local_endpoint(tmp_path):
    config = tmp_path / "openclaw.json"
    config.write_text(
        json.dumps(
            {
                "gateway": {"port": 18789, "auth": {"token": "gateway-private"}},
                "agents": {"defaults": {"model": {"primary": "provider/model"}}},
            }
        )
    )
    reviewer = reviewer_from_openclaw(config)
    assert reviewer.base_url == "http://127.0.0.1:18789/v1"
    assert reviewer.model_name == "openclaw"
    assert "gateway-private" not in repr(reviewer)
