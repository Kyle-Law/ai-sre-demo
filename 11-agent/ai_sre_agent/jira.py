"""Minimal Jira Cloud client (REST v2 for wiki-markup bodies, v3 for JQL search)."""

from __future__ import annotations

import json
import re
import time

import requests

from .audit import AuditLog

MAX_COMMENT = 30_000
ALERT_JSON_RE = re.compile(r"ALERT_JSON_BEGIN\s*\{code(?::json)?\}(.*?)\{code\}\s*ALERT_JSON_END", re.S)


class Jira:
    def __init__(self, base_url: str, email: str, token: str, project: str, audit: AuditLog, dry_run: bool = False):
        self.base_url = base_url
        self.project = project
        self.audit = audit
        self.dry_run = dry_run
        self.session = requests.Session()
        self.session.auth = (email, token)
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

    # -- plumbing ---------------------------------------------------------
    def _req(self, method: str, path: str, **kwargs):
        for attempt in range(4):
            resp = self.session.request(method, f"{self.base_url}{path}", timeout=30, **kwargs)
            if resp.status_code == 429 and attempt < 3:
                time.sleep(int(resp.headers.get("Retry-After", "2")))
                continue
            if resp.status_code >= 400:
                raise RuntimeError(f"Jira {method} {path} -> {resp.status_code}: {resp.text[:500]}")
            return resp.json() if resp.content else {}
        raise RuntimeError(f"Jira {method} {path}: rate limited")

    def browse_url(self, key: str) -> str:
        return f"{self.base_url}/browse/{key}"

    # -- reads ------------------------------------------------------------
    def search(self, jql: str, fields: str = "summary,labels,status,created") -> list[dict]:
        issues, token = [], None
        while True:
            params = {"jql": jql, "fields": fields, "maxResults": 50}
            if token:
                params["nextPageToken"] = token
            res = self._req("GET", "/rest/api/3/search/jql", params=params)
            issues.extend(res.get("issues", []))
            token = res.get("nextPageToken")
            if not token or res.get("isLast", True):
                return issues

    def triage_queue(self, label: str) -> list[dict]:
        jql = (f'project = "{self.project}" AND labels = "{label}" '
               f"AND statusCategory != Done ORDER BY created ASC")
        return self.search(jql)

    def get_project(self) -> dict:
        return self._req("GET", f"/rest/api/2/project/{self.project}")

    def get_issue(self, key: str) -> dict:
        return self._req(
            "GET", f"/rest/api/2/issue/{key}",
            params={"fields": "summary,description,labels,status,created,comment"},
        )

    @staticmethod
    def extract_alerts(issue: dict) -> list[dict]:
        """Alert payloads embedded by the alert bridge (description + correlated comments)."""
        texts = [issue.get("fields", {}).get("description") or ""]
        for c in issue.get("fields", {}).get("comment", {}).get("comments", []):
            texts.append(c.get("body") or "")
        alerts = []
        for text in texts:
            for block in ALERT_JSON_RE.findall(text):
                try:
                    alerts.append(json.loads(block))
                except json.JSONDecodeError:
                    continue
        return alerts

    # -- writes -----------------------------------------------------------
    def comment(self, key: str, body: str) -> None:
        body = body if len(body) <= MAX_COMMENT else body[: MAX_COMMENT - 40] + "\n\n_(comment truncated)_"
        self.audit.write("jira_comment", ticket=key, chars=len(body), dry_run=self.dry_run, output=body)
        if self.dry_run:
            print(f"\n===== [DRY RUN] Jira comment on {key} =====\n{body}\n")
            return
        self._req("POST", f"/rest/api/2/issue/{key}/comment", data=json.dumps({"body": body}))

    def add_labels(self, key: str, labels: list[str]) -> None:
        self.audit.write("jira_add_labels", ticket=key, labels=labels, dry_run=self.dry_run)
        if self.dry_run:
            return
        self._req("PUT", f"/rest/api/2/issue/{key}",
                  data=json.dumps({"update": {"labels": [{"add": l} for l in labels]}}))

    def transition(self, key: str, name: str) -> bool:
        """Move the issue through a transition matching `name` (transition or target status)."""
        if not name:
            return False
        res = self._req("GET", f"/rest/api/2/issue/{key}/transitions")
        wanted = name.strip().lower()
        for t in res.get("transitions", []):
            if t.get("name", "").lower() == wanted or t.get("to", {}).get("name", "").lower() == wanted:
                self.audit.write("jira_transition", ticket=key, to=name, dry_run=self.dry_run)
                if not self.dry_run:
                    self._req("POST", f"/rest/api/2/issue/{key}/transitions",
                              data=json.dumps({"transition": {"id": t["id"]}}))
                return True
        self.audit.write("jira_transition_unavailable", ticket=key, to=name,
                         available=[t.get("name") for t in res.get("transitions", [])])
        return False
