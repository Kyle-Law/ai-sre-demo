"""Append-only JSONL audit log of everything the agent does.

Every tool call the model makes (with arguments and a truncated result),
every external write (Jira comment, PR, transition) and every state change is
recorded here. Ship this file to your log platform for a full incident trail.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone

log = logging.getLogger("ai_sre_agent")


class AuditLog:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    def write(self, event: str, ticket: str | None = None, **fields) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": event,
            "ticket": ticket,
            **fields,
        }
        line = json.dumps(record, default=str)
        with self._lock, open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        log.info("%s %s", event, json.dumps({k: v for k, v in fields.items() if k != "output"}, default=str)[:400])
