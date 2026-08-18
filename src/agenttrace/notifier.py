from __future__ import annotations

import hashlib
import sqlite3
import subprocess
from collections.abc import Callable
from pathlib import Path

MAIL_SCRIPT = r'''
on run argv
    set recipientAddress to item 1 of argv
    set messageSubject to item 2 of argv
    set messageBody to item 3 of argv
    tell application "Mail"
        set outgoingMessage to make new outgoing message with properties {subject:messageSubject, content:messageBody & return, visible:false}
        tell outgoingMessage
            make new to recipient at end of to recipients with properties {address:recipientAddress}
            send
        end tell
    end tell
end run
'''


def notify_email_alerts(
    database: str | Path,
    recipient: str,
    *,
    test: bool = False,
    sender: Callable[[str, str, str], None] | None = None,
) -> int:
    """Send every previously unnotified monitor alert exactly once."""
    if "@" not in recipient or any(character in recipient for character in "\r\n"):
        raise ValueError("recipient must be a single email address")
    send = sender or _send_with_macos_mail
    if test:
        send(
            recipient,
            "AgentTrace: automatic alert delivery enabled",
            "The AgentTrace email notifier is installed and can send automatic alerts.",
        )
        return 1

    connection = sqlite3.connect(str(database), timeout=5)
    try:
        key = _state_key(recipient)
        row = connection.execute(
            "SELECT value FROM monitor_state WHERE key = ?", (key,)
        ).fetchone()
        last_id = int(row[0]) if row else 0
        alerts = connection.execute(
            "SELECT id, created_at, summary FROM monitor_alerts "
            "WHERE status='pending' AND id > ? ORDER BY id",
            (last_id,),
        ).fetchall()
        sent = 0
        for alert_id, created_at, summary in alerts:
            subject = f"AgentTrace high-confidence alert #{alert_id}"
            body = (
                f"AgentTrace found a candidate requiring human review at {created_at}.\n\n"
                f"{summary}\n\n"
                "This is evidence for review, not proof that an account is an AI agent."
            )
            send(recipient, subject, body)
            connection.execute(
                "INSERT INTO monitor_state(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(alert_id)),
            )
            connection.commit()
            sent += 1
        return sent
    finally:
        connection.close()


def _state_key(recipient: str) -> str:
    digest = hashlib.sha256(recipient.strip().casefold().encode()).hexdigest()[:20]
    return f"email_notified_alert_id:{digest}"


def _send_with_macos_mail(recipient: str, subject: str, body: str) -> None:
    subprocess.run(
        ["/usr/bin/osascript", "-e", MAIL_SCRIPT, recipient, subject, body],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
