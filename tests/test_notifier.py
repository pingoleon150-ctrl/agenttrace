import json
import sqlite3

from agenttrace.notifier import notify_email_alerts
from agenttrace.storage.sqlite import SQLiteStore


def test_notifier_sends_each_alert_once_without_storing_recipient(tmp_path):
    database = tmp_path / "monitor.db"
    with SQLiteStore(database):
        pass
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO monitor_alerts(fingerprint, created_at, summary, json) VALUES(?,?,?,?)",
        ("fingerprint", "2026-01-01T00:00:00Z", "review this", json.dumps({})),
    )
    connection.commit()
    connection.close()

    messages = []
    sender = lambda recipient, subject, body: messages.append((recipient, subject, body))
    assert notify_email_alerts(database, "alert@example.com", sender=sender) == 1
    assert notify_email_alerts(database, "alert@example.com", sender=sender) == 0
    assert len(messages) == 1
    assert "review this" in messages[0][2]

    connection = sqlite3.connect(database)
    state = connection.execute("SELECT key, value FROM monitor_state").fetchall()
    connection.close()
    assert state[0][1] == "1"
    assert "alert@example.com" not in state[0][0]


def test_test_delivery_does_not_require_database(tmp_path):
    messages = []
    sent = notify_email_alerts(
        tmp_path / "missing.db",
        "alert@example.com",
        test=True,
        sender=lambda *message: messages.append(message),
    )
    assert sent == 1
    assert "enabled" in messages[0][1]
