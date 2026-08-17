from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agenttrace.models import EvidenceBundle, Observation


@dataclass
class RepositoryRecord:
    repository: str
    last_checked_at: str
    last_event_time: str | None
    query_version: str
    detector_version: str
    observations: int
    max_score: float
    status: str


class RepositoryLedger:
    def __init__(self, root: str | Path = "ledger/repos"):
        self.root = Path(root)

    def path_for(self, repository: str) -> Path:
        parts = repository.strip().split("/", 1)
        if len(parts) != 2 or not all(_safe_component(part) for part in parts):
            raise ValueError(f"invalid repository name: {repository}")
        owner, name = (part.lower() for part in parts)
        return self.root / "github" / owner / f"{name}.json"

    def read(self, repository: str) -> RepositoryRecord | None:
        path = self.path_for(repository)
        if not path.exists():
            return None
        return RepositoryRecord(**json.loads(path.read_text()))

    def should_skip(
        self,
        repository: str,
        *,
        recheck_all: bool = False,
        recheck_repositories: set[str] | None = None,
        recheck_stale_days: int | None = None,
        now: datetime | None = None,
    ) -> bool:
        record = self.read(repository)
        if record is None or recheck_all:
            return False
        requested = {item.lower() for item in (recheck_repositories or set())}
        if repository.lower() in requested:
            return False
        if recheck_stale_days is not None:
            checked = datetime.fromisoformat(record.last_checked_at)
            current = now or datetime.now(UTC)
            if current - checked >= timedelta(days=max(0, recheck_stale_days)):
                return False
        return True

    def write(self, record: RepositoryRecord) -> Path:
        path = self.path_for(record.repository)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(record), indent=2, sort_keys=True) + "\n")
        return path


def _safe_component(value: str) -> bool:
    return (
        bool(value)
        and value not in {".", ".."}
        and all(character.isalnum() or character in {"-", "_", "."} for character in value)
    )


def update_ledger(
    ledger: RepositoryLedger,
    observations: list[Observation],
    bundles: list[EvidenceBundle],
    queries: list[str],
    detector_version: str,
) -> list[Path]:
    query_version = hashlib.sha256("\n".join(queries).encode()).hexdigest()
    repositories = sorted({obs.repository for obs in observations if obs.repository})
    written = []
    for repository in repositories:
        repo_observations = [obs for obs in observations if obs.repository == repository]
        repo_bundles = [
            bundle
            for bundle in bundles
            if any(obs.repository == repository for obs in bundle.observations)
        ]
        record = RepositoryRecord(
            repository=repository,
            last_checked_at=datetime.now(UTC).isoformat(),
            last_event_time=max(obs.event_time for obs in repo_observations).isoformat(),
            query_version=query_version,
            detector_version=detector_version,
            observations=len(repo_observations),
            max_score=max((bundle.score.score for bundle in repo_bundles), default=0.0),
            status="high_confidence"
            if any(bundle.score.reviewable for bundle in repo_bundles)
            else "no_high_confidence",
        )
        written.append(ledger.write(record))
    return written
