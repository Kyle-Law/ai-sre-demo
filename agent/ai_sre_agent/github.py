"""Minimal GitHub REST client. The token needs contents:write + pull_requests:write
on ONE repository. Branch protection guarantees the agent cannot merge."""

from __future__ import annotations

import base64
import re
import time

import requests

from .audit import AuditLog


class GitHub:
    def __init__(self, api_url: str, token: str, repo: str, base_branch: str, audit: AuditLog, dry_run: bool = False):
        self.api = api_url
        self.repo = repo
        self.base = base_branch
        self.audit = audit
        self.dry_run = dry_run
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def _req(self, method: str, path: str, ok=(200, 201), **kwargs):
        resp = self.session.request(method, f"{self.api}{path}", timeout=30, **kwargs)
        if resp.status_code not in ok:
            raise RuntimeError(f"GitHub {method} {path} -> {resp.status_code}: {resp.text[:400]}")
        return resp.json() if resp.content else {}

    # -- reads (used as model tools) ---------------------------------------
    def read_file(self, path: str, ref: str | None = None) -> str:
        data = self._req("GET", f"/repos/{self.repo}/contents/{path.lstrip('/')}",
                         params={"ref": ref or self.base})
        if isinstance(data, list):
            raise RuntimeError(f"{path} is a directory")
        return base64.b64decode(data["content"]).decode("utf-8")

    def list_dir(self, path: str) -> list[str]:
        data = self._req("GET", f"/repos/{self.repo}/contents/{path.strip('/')}", params={"ref": self.base})
        if not isinstance(data, list):
            return [data.get("path", path)]
        return [f"{item['path']}{'/' if item['type'] == 'dir' else ''}" for item in data]

    def recent_commits(self, path: str | None = None, limit: int = 10) -> list[dict]:
        params = {"sha": self.base, "per_page": min(limit, 30)}
        if path:
            params["path"] = path
        commits = self._req("GET", f"/repos/{self.repo}/commits", params=params)
        return [{
            "sha": c["sha"][:12],
            "author": (c.get("commit", {}).get("author") or {}).get("name"),
            "date": (c.get("commit", {}).get("author") or {}).get("date"),
            "message": c.get("commit", {}).get("message", "").splitlines()[0][:200],
        } for c in commits]

    def commit_diff(self, sha: str) -> str:
        if not re.fullmatch(r"[0-9a-fA-F]{6,40}", sha):
            raise RuntimeError("sha must be a hex commit id")
        c = self._req("GET", f"/repos/{self.repo}/commits/{sha}")
        parts = [f"commit {c['sha']}\nAuthor: {c['commit']['author']['name']}\n"
                 f"Date: {c['commit']['author']['date']}\n\n    {c['commit']['message']}\n"]
        for f in c.get("files", []):
            parts.append(f"--- {f['filename']} ({f['status']})\n{f.get('patch', '(binary or too large)')}")
        return "\n".join(parts)

    # -- PR lifecycle --------------------------------------------------------
    def open_pull_request(self, branch: str, files: dict[str, str], title: str, body: str,
                          labels: list[str], reviewers: list[str]) -> dict:
        """Create branch, commit each file, open PR. Returns {'number', 'html_url', 'branch'}."""
        self.audit.write("github_open_pr", branch=branch, files=list(files), title=title, dry_run=self.dry_run)
        if self.dry_run:
            print(f"\n===== [DRY RUN] PR '{title}' on {branch} =====\n{body}\n")
            return {"number": 0, "html_url": "(dry-run)", "branch": branch}

        base_sha = self._req("GET", f"/repos/{self.repo}/git/ref/heads/{self.base}")["object"]["sha"]
        try:
            self._req("POST", f"/repos/{self.repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": base_sha})
        except RuntimeError as exc:
            if "422" not in str(exc):
                raise
            branch = f"{branch}-{int(time.time())}"
            self._req("POST", f"/repos/{self.repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": base_sha})

        for path, content in files.items():
            existing = self.session.get(f"{self.api}/repos/{self.repo}/contents/{path}",
                                        params={"ref": branch}, timeout=30)
            payload = {
                "message": f"{title}\n\nFile: {path}",
                "content": base64.b64encode(content.encode()).decode(),
                "branch": branch,
            }
            if existing.status_code == 200:
                payload["sha"] = existing.json()["sha"]
            self._req("PUT", f"/repos/{self.repo}/contents/{path}", json=payload)

        pr = self._req("POST", f"/repos/{self.repo}/pulls",
                       json={"title": title, "head": branch, "base": self.base, "body": body,
                             "maintainer_can_modify": True})
        if labels:
            try:
                self._req("POST", f"/repos/{self.repo}/issues/{pr['number']}/labels", json={"labels": labels})
            except RuntimeError as exc:
                self.audit.write("github_label_failed", error=str(exc))
        if reviewers:
            try:
                self._req("POST", f"/repos/{self.repo}/pulls/{pr['number']}/requested_reviewers",
                          json={"reviewers": reviewers})
            except RuntimeError as exc:
                self.audit.write("github_reviewers_failed", error=str(exc))
        return {"number": pr["number"], "html_url": pr["html_url"], "branch": branch}

    def get_pull(self, number: int) -> dict:
        return self._req("GET", f"/repos/{self.repo}/pulls/{number}")

    def get_reviews(self, number: int) -> list[dict]:
        return self._req("GET", f"/repos/{self.repo}/pulls/{number}/reviews", params={"per_page": 100})

    def is_ancestor(self, ancestor_sha: str, descendant_sha: str) -> bool:
        """True if ancestor_sha is contained in descendant_sha's history."""
        if ancestor_sha == descendant_sha:
            return True
        res = self._req("GET", f"/repos/{self.repo}/compare/{ancestor_sha}...{descendant_sha}")
        return res.get("status") in {"ahead", "identical"}
