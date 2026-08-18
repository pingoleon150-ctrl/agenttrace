from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any, Protocol

import httpx

from agenttrace.models import EvidenceBundle

SYSTEM_PROMPT = """You are the evidence analyst for AgentTrace, an open research monitor.
Classify publicly observable coordination without assuming that GitHub accounts are autonomous
agents. Distinguish: ordinary automation, human collaboration, AI-assisted collaboration,
semi-autonomous multi-agent collaboration, and evidence of fully autonomous agent collaboration.
Return strict JSON only. Never claim identity, company affiliation, maliciousness, or a model
version without direct evidence. Treat the detector score as review priority, not probability.
"""

REQUIRED_KEYS = {
    "classification",
    "autonomy_level",
    "confidence",
    "summary",
    "intent",
    "human_risk",
    "company_affiliation",
    "agents_identified",
    "models_identified",
    "evidence_for",
    "evidence_against",
    "recommended_disposition",
}

CLASSIFICATION_DEFAULTS: dict[str, Any] = {
    "classification": "inconclusive",
    "autonomy_level": "unknown",
    "confidence": "low",
    "summary": "The model did not provide this field.",
    "intent": "Not established.",
    "human_risk": "Not established.",
    "company_affiliation": "Not established.",
    "agents_identified": [],
    "models_identified": [],
    "evidence_for": [],
    "evidence_against": ["The classifier omitted one or more requested fields."],
    "recommended_disposition": "manual_review",
}

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_ -]?key|access[_ -]?token|bearer|password|passwd)\s*[:=]\s*\S+"),
    re.compile(
        r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
    re.compile(r"\bgh[opurs]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
]


class BundleReviewer(Protocol):
    reviewer_name: str
    model_name: str

    async def classify(self, bundle: EvidenceBundle) -> dict[str, Any]: ...


@dataclass(frozen=True)
class OpenAICompatibleReviewer:
    base_url: str
    api_key: str = field(repr=False)
    model_name: str
    reviewer_name: str
    timeout_seconds: float = 90.0

    async def classify(self, bundle: EvidenceBundle) -> dict[str, Any]:
        payload = public_bundle_payload(bundle)
        request = {
            "model": self.model_name,
            "temperature": 0,
            "max_tokens": 1200,
            "stream": False,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Classify this public evidence bundle. Required JSON keys: "
                        + ", ".join(sorted(REQUIRED_KEYS))
                        + "\n\n"
                        + json.dumps(payload, ensure_ascii=False)
                    ),
                },
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url.rstrip('/')}/chat/completions", json=request, headers=headers
            )
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        result = _parse_json_object(content)
        for key in REQUIRED_KEYS - result.keys():
            result[key] = CLASSIFICATION_DEFAULTS[key]
        return result


def reviewer_from_openclaw(
    config_path: str | Path,
    provider_name: str = "gateway",
    model_name: str | None = None,
) -> OpenAICompatibleReviewer:
    path = Path(config_path).expanduser()
    config = json.loads(path.read_text())
    if provider_name == "gateway":
        gateway = config.get("gateway", {})
        token = _resolve_secret(gateway.get("auth", {}).get("token"))
        port = int(gateway.get("port") or 18789)
        selected_model = model_name or "openclaw"
        if not token or not selected_model:
            raise ValueError("OpenClaw gateway authentication or primary model is incomplete")
        return OpenAICompatibleReviewer(
            base_url=f"http://127.0.0.1:{port}/v1",
            api_key=token,
            model_name=selected_model,
            reviewer_name="openclaw:gateway",
        )
    providers = config.get("models", {}).get("providers", {})
    provider = providers.get(provider_name)
    if not isinstance(provider, dict):
        raise TypeError(f"OpenClaw provider not found: {provider_name}")
    api_key = _resolve_secret(provider.get("apiKey"))
    base_url = str(provider.get("baseUrl") or "").strip()
    configured_models = provider.get("models") or []
    selected_model = model_name or (
        str(configured_models[0].get("id")) if configured_models else ""
    )
    if not api_key or not base_url or not selected_model:
        raise ValueError(f"OpenClaw provider {provider_name} is incomplete")
    return OpenAICompatibleReviewer(
        base_url=base_url,
        api_key=api_key,
        model_name=selected_model,
        reviewer_name=f"openclaw:{provider_name}",
    )


def public_bundle_payload(bundle: EvidenceBundle, max_observations: int = 20) -> dict[str, Any]:
    observations = sorted(bundle.observations, key=lambda item: item.event_time)[-max_observations:]
    return {
        "cluster_id": bundle.cluster_id,
        "created_at": bundle.created_at.isoformat(),
        "actors": bundle.actors,
        "detector": bundle.score.model_dump(),
        "signals": [signal.model_dump() for signal in bundle.signals],
        "observations": [
            {
                "event_time": item.event_time.isoformat(),
                "actor": item.actor,
                "actor_type": item.metadata.get("actor_type"),
                "github_app": item.metadata.get("github_app_slug"),
                "event_type": item.event_type,
                "repository": item.repository,
                "thread_id": item.thread_id,
                "text": redact_public_text(item.text or "")[:2000],
                "url": item.provenance.url,
            }
            for item in observations
        ],
        "instruction": (
            "All evidence is public, but content was redacted for common credential patterns. "
            "Identify uncertainty and benign alternatives."
        ),
    }


def redact_public_text(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def render_findings_report(findings: list[dict[str, Any]]) -> str:
    generated = datetime.now(UTC).isoformat()
    lines = [
        "# AgentTrace Public Findings",
        "",
        f"_Generated from the local review ledger at {generated}._",
        "",
        "> These findings prioritize public evidence for review. They do not prove that an account",
        "> is autonomous, identify the human behind an account, or establish malicious intent.",
        "",
        "## Summary",
        "",
        "| ID | Status | Score | Confidence | Classification | Actors |",
        "|---:|---|---:|---|---|---|",
    ]
    for finding in findings:
        summary = finding["summary"]
        classification = finding["classification"] or {}
        actors = ", ".join(f"`{actor}`" for actor in summary.get("actors", []))
        lines.append(
            f"| {finding['id']} | {finding['status']} | {summary.get('score', '')} | "
            f"{summary.get('confidence', '')} | "
            f"{_cell(classification.get('classification', 'manual review'))} | {actors} |"
        )
    for finding in findings:
        summary = finding["summary"]
        classification = finding["classification"]
        lines.extend(["", f"## Finding {finding['id']}", ""])
        lines.append(f"- **Status:** `{finding['status']}`")
        lines.append(f"- **Detected:** {finding['created_at']}")
        lines.append(f"- **Score:** {summary.get('score')} ({summary.get('confidence')})")
        lines.append(
            "- **Actors:** "
            + ", ".join(f"`{actor}`" for actor in summary.get("actors", []))
        )
        lines.append(f"- **Cluster:** `{summary.get('cluster_id', '')}`")
        if classification:
            lines.extend(
                [
                    f"- **Classification:** {_text(classification.get('classification'))}",
                    f"- **Autonomy:** {_text(classification.get('autonomy_level'))}",
                    f"- **LLM confidence:** {_text(classification.get('confidence'))}",
                    f"- **Disposition:** {_text(classification.get('recommended_disposition'))}",
                    "",
                    f"**Summary:** {_text(classification.get('summary'))}",
                    "",
                    f"**Intent:** {_text(classification.get('intent'))}",
                    "",
                    f"**Potential human risk:** {_text(classification.get('human_risk'))}",
                    "",
                    f"**Company affiliation:** {_text(classification.get('company_affiliation'))}",
                    "",
                    f"**Agents identified:** {_json_text(classification.get('agents_identified'))}",
                    "",
                    f"**Models identified:** {_json_text(classification.get('models_identified'))}",
                    "",
                    "**Evidence supporting the classification:**",
                    *_bullets(classification.get("evidence_for")),
                    "",
                    "**Counterevidence and uncertainty:**",
                    *_bullets(classification.get("evidence_against")),
                    "",
                    (
                        f"_Classifier: `{finding['reviewer']}` / `{finding['model']}` at "
                        f"{finding['classification_created_at']}._"
                    ),
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "This historical finding was handled before automated LLM classification was enabled.",
                ]
            )
        provenance = summary.get("provenance", [])
        if provenance:
            lines.extend(["", "**Public provenance:**"])
            lines.extend(f"- {url}" for url in provenance[:20])
    lines.extend(
        [
            "",
            "---",
            "",
            "This report contains public evidence summaries only. Common credential patterns are",
            "redacted before LLM review, and API credentials are never written to this file.",
            "",
        ]
    )
    return "\n".join(lines)


def write_findings_report(path: str | Path, findings: list[dict[str, Any]]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(render_findings_report(findings))
    temporary.replace(destination)


def render_findings_html(findings: list[dict[str, Any]]) -> str:
    generated = datetime.now(UTC).isoformat()
    cards = []
    for finding in findings:
        summary = finding["summary"]
        classification = finding["classification"] or {}
        actors = "".join(
            f"<span class=\"pill\">{escape(str(actor))}</span>"
            for actor in summary.get("actors", [])
        )
        provenance = "".join(
            f'<li><a href="{escape(str(url), quote=True)}" target="_blank" '
            f'rel="noopener noreferrer">{escape(str(url))}</a></li>'
            for url in summary.get("provenance", [])[:20]
        )
        def value(
            key: str,
            fallback: str = "Not established.",
            values: dict[str, Any] = classification,
        ) -> str:
            return escape(_text(values.get(key, fallback)))

        details = (
            f"<dl><dt>Classification</dt><dd>{value('classification', 'Manual review')}</dd>"
            f"<dt>Autonomy</dt><dd>{value('autonomy_level')}</dd>"
            f"<dt>LLM confidence</dt><dd>{value('confidence')}</dd>"
            f"<dt>Intent</dt><dd>{value('intent')}</dd>"
            f"<dt>Potential human risk</dt><dd>{value('human_risk')}</dd>"
            f"<dt>Company affiliation</dt><dd>{value('company_affiliation')}</dd></dl>"
            if classification
            else "<p class=\"muted\">Historical finding reviewed before LLM classification.</p>"
        )
        cards.append(
            f'<article id="finding-{finding["id"]}"><header><div><span class="eyebrow">'
            f'Finding {finding["id"]}</span><h2>{value("classification", "Manual review")}</h2>'
            f'</div><span class="status">{escape(str(finding["status"]))}</span></header>'
            f'<div class="metrics"><b>Score {escape(str(summary.get("score", "")))}</b>'
            f'<span>{escape(str(summary.get("confidence", "")))} confidence</span>'
            f'<span>{escape(str(finding["created_at"]))}</span></div>'
            f'<div class="actors">{actors}</div>{details}'
            f'<p>{value("summary", "Public evidence awaiting automated classification.")}</p>'
            f'<details><summary>Public provenance ({len(summary.get("provenance", []))})</summary>'
            f'<ul>{provenance}</ul></details></article>'
        )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<meta http-equiv="refresh" content="300"><title>AgentTrace Public Findings</title>
<style>
:root{{--bg:#07111f;--panel:#101d2e;--line:#26364b;--text:#edf4ff;--muted:#9fb0c5;--accent:#5eead4}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(145deg,#07111f,#0d1728);color:var(--text);font:15px/1.55 system-ui,sans-serif}}
main{{max-width:1100px;margin:auto;padding:48px 20px 80px}}h1{{font-size:clamp(2rem,6vw,4.5rem);margin:.1em 0}}h2{{margin:.2em 0;font-size:1.35rem}}
.lead,.muted{{color:var(--muted)}}.summary{{display:flex;gap:12px;flex-wrap:wrap;margin:28px 0}}.summary span,.pill,.status{{border:1px solid var(--line);border-radius:999px;padding:5px 10px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:18px}}article{{background:rgba(16,29,46,.92);border:1px solid var(--line);border-radius:18px;padding:22px;box-shadow:0 20px 50px #0004}}
article header{{display:flex;justify-content:space-between;gap:16px}}.eyebrow{{color:var(--accent);font-size:.75rem;text-transform:uppercase;letter-spacing:.12em}}.status{{height:max-content;color:var(--accent)}}
.metrics,.actors{{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0;color:var(--muted)}}dl{{display:grid;grid-template-columns:minmax(115px,.5fr) 1fr;gap:8px 14px}}dt{{color:var(--muted)}}dd{{margin:0;overflow-wrap:anywhere}}a{{color:#7dd3fc}}ul{{padding-left:20px;overflow-wrap:anywhere}}footer{{margin-top:30px;color:var(--muted)}}
</style></head><body><main><span class="eyebrow">Continuous public evidence review</span><h1>AgentTrace Findings</h1>
<p class="lead">Research candidates, not proof of autonomous agents or malicious intent.</p>
<div class="summary"><span>{len(findings)} total findings</span><span>Updated {escape(generated)}</span><span>Auto-refresh: 5 minutes</span></div>
<section class="grid">{''.join(cards) or '<article><h2>No findings yet</h2><p class="muted">The monitor is watching for high-priority evidence.</p></article>'}</section>
<footer>Only public evidence summaries are served. Credentials and the local database are never included.</footer></main></body></html>"""


def write_findings_html(path: str | Path, findings: list[dict[str, Any]]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(render_findings_html(findings))
    temporary.replace(destination)


def _resolve_secret(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", value.strip())
    return os.getenv(match.group(1), "") if match else value.strip()


def _parse_json_object(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise TypeError("classifier response must be a JSON object")
    return parsed


def _text(value: Any) -> str:
    return redact_public_text(str(value or "Not established."))


def _json_text(value: Any) -> str:
    if isinstance(value, (list, dict)):
        return redact_public_text(json.dumps(value, ensure_ascii=False))
    return _text(value)


def _bullets(value: Any) -> list[str]:
    items = value if isinstance(value, list) else [value]
    return [f"- {_text(item)}" for item in items if item]


def _cell(value: Any) -> str:
    return _text(value).replace("|", "\\|").replace("\n", " ")
