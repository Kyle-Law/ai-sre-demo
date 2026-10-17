#!/usr/bin/env python3
"""Create the agent's GitHub App from a manifest (one browser click), save its private key.

    python3 scripts/create-github-app.py [--name kyle-law-ai-sre-agent]

Why an App and not a token on your own account: PRs opened by an App are authored by
`<slug>[bot]`, so you (the repo owner) can approve them, and no second GitHub account
or email is needed. The App is private (installable only on your account) and asks for
Contents + Pull requests write on the repos you install it on - nothing else.

Flow: a local page auto-submits the manifest to GitHub -> you click "Create GitHub App"
-> GitHub redirects back here with a one-time code -> we exchange it for the App id and
private key. Then you install the App on the demo repo (link printed at the end).
"""

from __future__ import annotations

import argparse
import html
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = 8765


def demo_env() -> dict[str, str]:
    env = {}
    path = ROOT / "demo.env"
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and not key.strip().startswith("#"):
                env[key.strip()] = value.split("#", 1)[0].strip()
    return env


def main() -> int:
    env = demo_env()
    repo = env.get("GITHUB_REPO", "")
    if "/" not in repo or repo.startswith("your-org/"):
        sys.exit("Set GITHUB_REPO=owner/name in demo.env first.")
    owner = repo.split("/")[0]
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", default=f"{owner.lower()}-ai-sre-agent"[:34],
                   help="App name; must be unique across GitHub (max 34 chars)")
    p.add_argument("--org", help="create under this organization instead of your user account")
    p.add_argument("--key-out", default=str(ROOT / "github-app.pem"))
    args = p.parse_args()

    state = secrets.token_urlsafe(16)
    manifest = {
        "name": args.name,
        "url": f"https://github.com/{repo}",
        "description": "AI SRE demo agent: opens remediation PRs for human review. Cannot merge.",
        "hook_attributes": {"url": "https://example.com/unused", "active": False},
        "redirect_url": f"http://127.0.0.1:{PORT}/callback",
        "public": False,
        "default_permissions": {"contents": "write", "pull_requests": "write", "metadata": "read"},
        "default_events": [],
    }
    base = f"https://github.com/organizations/{args.org}" if args.org else "https://github.com"
    action = f"{base}/settings/apps/new?state={state}"
    page = (f'<!doctype html><meta charset="utf-8"><title>Create GitHub App</title>'
            f'<form id="f" method="post" action="{html.escape(action)}">'
            f'<input type="hidden" name="manifest" value="{html.escape(json.dumps(manifest))}">'
            f'<button>Continue to GitHub</button></form><script>document.getElementById("f").submit()</script>')
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _send(self, body: str, status: int = 200):
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path == "/":
                return self._send(page)
            if url.path != "/callback":
                return self._send("not found", 404)
            q = urllib.parse.parse_qs(url.query)
            if q.get("state", [""])[0] != state or "code" not in q:
                return self._send("State mismatch - rerun the script.", 400)
            req = urllib.request.Request(
                f"https://api.github.com/app-manifests/{q['code'][0]}/conversions", method="POST",
                headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                result.update(json.load(resp))
            self._send(f"<p>App <b>{html.escape(result['slug'])}</b> created. "
                       f"Return to the terminal.</p>")

    server = HTTPServer(("127.0.0.1", PORT), Handler)
    start = f"http://127.0.0.1:{PORT}/"
    print(f"Opening {start} - sign in to GitHub as {args.org or owner} and click 'Create GitHub App'.")
    webbrowser.open(start)
    while not result:
        server.handle_request()
    server.server_close()

    key_path = Path(args.key_out)
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(result["pem"])

    slug = result["slug"]
    print(f"""
Created GitHub App '{slug}' (id {result['id']}). Private key: {key_path} (0600, git-ignored)

1. Install it on ONLY the demo repo:
     https://github.com/apps/{slug}/installations/new
   -> "Only select repositories" -> {repo}

2. demo.env (CI scope guard + branch protection script):
     GITHUB_AGENT_LOGIN={slug}[bot]

3. agent.env (the agent's GitHub identity):
     GITHUB_APP_ID={result['id']}
     GITHUB_APP_PRIVATE_KEY_PATH={key_path}
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
