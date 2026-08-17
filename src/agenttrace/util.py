from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

URL_RE = re.compile(r"https?://[^\s<>'\")\]]+")
FENCED_CODE_RE = re.compile(r"```(?:[a-zA-Z0-9_+-]+)?\n(.*?)```", re.DOTALL)


def utcnow() -> datetime:
    return datetime.now(UTC)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def extract_urls(text: str | None) -> list[str]:
    if not text:
        return []
    return sorted(set(URL_RE.findall(text)))


def extract_code_blocks(text: str | None) -> list[str]:
    if not text:
        return []
    return [block.strip() for block in FENCED_CODE_RE.findall(text) if block.strip()]
