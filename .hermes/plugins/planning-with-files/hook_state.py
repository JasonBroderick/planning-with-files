from __future__ import annotations

import hashlib
import threading
from typing import Dict, List

_SESSION_REMINDERS: Dict[str, List[str]] = {}
_REMINDER_LOCK = threading.Lock()


def _session_key(session_id: str) -> str:
    value = str(session_id or "").strip()
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def add_reminder(session_id: str, message: str) -> None:
    session_key = _session_key(session_id)
    if not session_key or not message:
        return
    with _REMINDER_LOCK:
        bucket = _SESSION_REMINDERS.setdefault(session_key, [])
        if message not in bucket:
            bucket.append(message)


def clear_reminders(session_id: str) -> None:
    session_key = _session_key(session_id)
    if not session_key:
        return
    with _REMINDER_LOCK:
        _SESSION_REMINDERS.pop(session_key, None)


def pop_reminders(session_id: str) -> list[str]:
    session_key = _session_key(session_id)
    if not session_key:
        return []
    with _REMINDER_LOCK:
        return _SESSION_REMINDERS.pop(session_key, [])
