from datetime import UTC, datetime, timedelta

from agenttrace.ledger import RepositoryLedger, RepositoryRecord


def record(repository: str, checked: datetime) -> RepositoryRecord:
    return RepositoryRecord(
        repository=repository,
        last_checked_at=checked.isoformat(),
        last_event_time=None,
        query_version="queries-v1",
        detector_version="0.2.0",
        observations=12,
        max_score=0.31,
        status="no_high_confidence",
    )


def test_existing_repository_is_skipped_by_default(tmp_path):
    ledger = RepositoryLedger(tmp_path)
    ledger.write(record("Owner/Repo", datetime(2026, 8, 17, tzinfo=UTC)))

    assert ledger.should_skip("owner/repo")
    assert not ledger.should_skip("owner/repo", recheck_all=True)
    assert not ledger.should_skip("owner/repo", recheck_repositories={"OWNER/REPO"})


def test_stale_override_is_explicit(tmp_path):
    ledger = RepositoryLedger(tmp_path)
    now = datetime(2026, 8, 17, tzinfo=UTC)
    ledger.write(record("owner/repo", now - timedelta(days=31)))

    assert ledger.should_skip("owner/repo", now=now)
    assert not ledger.should_skip("owner/repo", recheck_stale_days=30, now=now)
