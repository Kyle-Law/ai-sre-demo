"""Incident lifecycle stages and time helpers. The store is incluster.CRStateStore."""

from __future__ import annotations

from datetime import datetime, timezone

# Lifecycle of a ticket handled by the agent
NEW = "NEW"
DIAGNOSING = "DIAGNOSING"
PR_OPEN = "PR_OPEN"
MERGED = "MERGED"
SYNCED = "SYNCED"
VERIFIED = "VERIFIED"   # fixed by the agent's PR, verified
RESOLVED = "RESOLVED"   # escalated, then fixed by a human; the agent verified and closed it
ESCALATED = "ESCALATED"
FAILED = "FAILED"
ACTIVE_STAGES = (NEW, DIAGNOSING, PR_OPEN, MERGED, SYNCED)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    # Jira uses +0000 (no colon); Python 3.11+ fromisoformat accepts both.
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        try:
            dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z")
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
