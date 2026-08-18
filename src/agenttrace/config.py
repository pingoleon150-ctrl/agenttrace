from __future__ import annotations

import os
from dataclasses import dataclass

from agenttrace import __version__


@dataclass(frozen=True)
class Settings:
    github_token: str | None = None
    db_path: str = "agenttrace.db"
    user_agent: str = (
        f"AgentTrace/{__version__} (+https://github.com/pingoleon150-ctrl/agenttrace)"
    )
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            github_token=os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN"),
            db_path=os.getenv("AGENTTRACE_DB", "agenttrace.db"),
            user_agent=os.getenv("AGENTTRACE_USER_AGENT", cls.user_agent),
            timeout_seconds=float(os.getenv("AGENTTRACE_TIMEOUT", "30")),
        )
