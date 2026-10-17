"""Minimal GitHub REST client. Credentials need contents:write + pull_requests:write
on ONE repository. Branch protection guarantees the agent cannot merge.

Preferred identity is a GitHub App (PRs are authored by `<app-slug>[bot]`, so the
repo owner can approve them and no second user account is needed). A plain token
(GITHUB_TOKEN) still works for bot-user setups."""

from __future__ import annotations

import base64
import re
import time
from datetime import datetime
from pathlib import Path

import jwt
import requests

from .audit import AuditLog

_GH_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
# Installation tokens are narrowed to exactly what the agent needs, even if the
# App itself was (mis)configured with more.
APP_TOKEN_PERMISSIONS = {"contents": "write", "pull_requests": "write", "metadata": "read"}


class AppAuth(requests.auth.AuthBase):
    """Authenticate as a GitHub App installation. Signs a short JWT with the App's
    private key, exchanges it for a 1-hour installation token scoped to one repo,
    and renews that token 5 minutes before it expires."""

    def __init__(self, api_url: str, app_id: str, private_key: str, repo: str,
                 installation_id: str = "", session: requests.Session | None = None, clock=time.time):
        self.api = api_url
        self.app_id = str(app_id)
        self.private_key = private_key
        self.repo = repo
        self.installation_id = str(installation_id or "")
        self.session = session or requests.Session()
        self.clock = clock
        self._token = ""
        self._expires = 0.0

    def _app_jwt(self) -> str:
        now = int(self.clock())
        # iat backdated for clock drift; GitHub caps exp at 10 minutes.
        return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": self.app_id}, self.private_key, algorithm="RS256")

    def _call(self, method: str, path: str, **kwargs) -> dict:
        headers = {**_GH_HEADERS, "Authorization": f"Bearer {self._app_jwt()}"}
        resp = self.session.request(method, f"{self.api}{path}", headers=headers, timeout=30, **kwargs)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"GitHub App {method} {path} -> {resp.status_code}: {resp.text[:400]}")
        return resp.json()

    def token(self) -> str:
        if self._token and self.clock() < self._expires - 300:
            return self._token
        if not self.installation_id:
            # 404 here means the App is not installed on the repo yet.
            self.installation_id = str(self._call("GET", f"/repos/{self.repo}/installation")["id"])
        data = self._call("POST", f"/app/installations/{self.installation_id}/access_tokens",
                          json={"repositories": [self.repo.split("/", 1)[1]], "permissions": APP_TOKEN_PERMISSIONS})
        self._token = data["token"]
        self._expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")).timestamp()
        return self._token

    def __call__(self, r):
        r.headers["Authorization"] = f"Bearer {self.token()}"
        return r


def auth_from_config(cfg) -> str | AppAuth:
    if cfg.github_app_id:
        key = Path(cfg.github_app_private_key_path).expanduser().read_text()
        return AppAuth(cfg.github_api_url, cfg.github_app_id, key, cfg.github_repo, cfg.github_app_installation_id)
    return cfg.github_token


class GitHub:
    def __init__(self, api_url: str, auth: str | requests.auth.AuthBase, repo: str, base_branch: str,
                 audit: AuditLog, dry_run: bool = False):
        self.api = api_url
        self.repo = repo
        self.base = base_branch
        self.audit = audit
        self.dry_run = dry_run
        self.session = requests.Session()
        self.session.headers.update(_GH_HEADERS)
        if isinstance(auth, str):
            self.session.headers["Authorization"] = f"Bearer {auth}"
        else:
            self.session.auth = auth

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
