"""Tiny SQLite store: one row per incident ticket, data kept as JSON."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
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


class StateStore:
    def __init__(self, path: str):
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS incidents ("
            " key TEXT PRIMARY KEY, stage TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        self.conn.commit()

    def get(self, key: str) -> dict | None:
        row = self.conn.execute("SELECT stage, data FROM incidents WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        data = json.loads(row[1])
        data["stage"] = row[0]
        data["key"] = key
        return data

    def put(self, key: str, stage: str, data: dict) -> dict:
        data = {k: v for k, v in data.items() if k not in {"stage", "key"}}
        with self._lock:
            self.conn.execute(
                "INSERT INTO incidents(key, stage, data, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET stage=excluded.stage, data=excluded.data, updated_at=excluded.updated_at",
                (key, stage, json.dumps(data), now_iso()),
            )
            self.conn.commit()
        return {**data, "stage": stage, "key": key}

    def update(self, key: str, stage: str | None = None, **fields) -> dict:
        current = self.get(key) or {}
        new_stage = stage or current.get("stage", NEW)
        current.update(fields)
        return self.put(key, new_stage, current)

    def in_stage(self, *stages: str) -> list[dict]:
        marks = ",".join("?" * len(stages))
        rows = self.conn.execute(f"SELECT key FROM incidents WHERE stage IN ({marks})", stages).fetchall()
        return [self.get(r[0]) for r in rows]

    def all(self) -> list[dict]:
        rows = self.conn.execute("SELECT key FROM incidents ORDER BY updated_at DESC").fetchall()
        return [self.get(r[0]) for r in rows]
