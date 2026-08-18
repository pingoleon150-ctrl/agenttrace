import asyncio
import json

import httpx

from agenttrace.reviewer import (
    OpenAICompatibleReviewer,
    redact_public_text,
    render_findings_html,
    reviewer_from_openclaw,
)


def test_classifier_fills_omitted_json_fields(monkeypatch):
    async def fake_post(self, url, json, headers):
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"classification":"automation"}'}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    reviewer = OpenAICompatibleReviewer("http://example.test/v1", "private", "model", "test")
    bundle = type("Bundle", (), {})()
    monkeypatch.setattr("agenttrace.reviewer.public_bundle_payload", lambda value: {})
    result = asyncio.run(reviewer.classify(bundle))
    assert result["classification"] == "automation"
    assert result["autonomy_level"] == "unknown"
    assert result["recommended_disposition"] == "manual_review"


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


def test_html_report_escapes_public_evidence_and_contains_no_secrets():
    html = render_findings_html(
        [{
            "id": 7,
            "status": "reviewed",
            "created_at": "2026-08-18T00:00:00Z",
            "summary": {
                "score": 0.91,
                "confidence": "high",
                "actors": ["<script>alert(1)</script>"],
                "provenance": ["https://example.test/?x=<unsafe>"],
            },
            "classification": {"classification": "AI-assisted collaboration"},
            "reviewer": "openclaw:gateway",
            "model": "openclaw",
            "classification_created_at": "2026-08-18T00:01:00Z",
        }]
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "Content-Security-Policy" in html
