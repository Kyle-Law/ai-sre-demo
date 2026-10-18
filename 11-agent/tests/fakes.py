"""In-memory fakes for Jira, GitHub, kubectl, Grafana and the Anthropic client."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace

BASE_DEPLOY = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: checkout
  namespace: shop
spec:
  template:
    spec:
      containers:
        - name: checkout
          resources:
            limits:
              memory: 64Mi
"""
FIXED_DEPLOY = BASE_DEPLOY.replace("memory: 64Mi", "memory: 256Mi")

ALERT = {
    "alertname": "ContainerOOMKilled",
    "status": "firing",
    "startsAt": "2026-10-17T06:00:00Z",
    "labels": {"alertname": "ContainerOOMKilled", "namespace": "shop", "workload": "checkout",
               "severity": "critical", "ai_triage": "true"},
}


class FakeJira:
    def __init__(self):
        self.comments: dict[str, list[str]] = {}
        self.labels: dict[str, list[str]] = {}
        self.transitions: list[tuple[str, str]] = []
        self.queue = [{"key": "INC-1"}]
        self.closed: set[str] = set()   # tickets a human has already moved to a done status

    def browse_url(self, key):
        return f"https://jira.example/browse/{key}"

    def triage_queue(self, label):
        return list(self.queue)

    def get_issue(self, key):
        desc = ("h3. alert\nALERT_JSON_BEGIN\n{code:json}\n" + json.dumps(ALERT) + "\n{code}\nALERT_JSON_END")
        return {"key": key, "fields": {"summary": "[CRITICAL] ContainerOOMKilled: shop/checkout",
                                       "description": desc, "created": "2026-10-17T06:00:20.000+0000",
                                       "status": {"statusCategory": {"key": "done" if key in self.closed else "indeterminate"}},
                                       "comment": {"comments": []}}}

    extract_alerts = staticmethod(__import__("ai_sre_agent.jira", fromlist=["Jira"]).Jira.extract_alerts)

    def comment(self, key, body):
        self.comments.setdefault(key, []).append(body)

    def add_labels(self, key, labels):
        self.labels.setdefault(key, []).extend(labels)

    def transition(self, key, name):
        self.transitions.append((key, name))
        return True


class FakeGitHub:
    def __init__(self):
        self.files = {"06-demo-app/manifests/deployment.yaml": BASE_DEPLOY}
        self.prs: dict[int, dict] = {}
        self.opened: list[dict] = []
        self.reviews: dict[int, list] = {}

    def read_file(self, path, ref=None):
        if path not in self.files:
            raise RuntimeError("404")
        return self.files[path]

    def list_dir(self, path):
        return [p for p in self.files if p.startswith(path)]

    def recent_commits(self, path=None, limit=10):
        return [{"sha": "abc123def456", "author": "dev", "date": "2026-10-17T05:58:00Z",
                 "message": "chore(checkout): rightsize memory limit per FinOps report"}]

    def commit_diff(self, sha):
        return "-              memory: 256Mi\n+              memory: 64Mi"

    def open_pull_request(self, branch, files, title, body, labels, reviewers):
        n = len(self.prs) + 1
        self.prs[n] = {"number": n, "html_url": f"https://github.example/pr/{n}", "merged": False,
                       "state": "open", "title": title}
        self.opened.append({"branch": branch, "files": files, "title": title, "body": body})
        return {"number": n, "html_url": self.prs[n]["html_url"], "branch": branch}

    def get_pull(self, n):
        return self.prs[n]

    def get_reviews(self, n):
        return self.reviews.get(n, [])

    def is_ancestor(self, a, b):
        return True


class FakeKube:
    def __init__(self):
        self.healthy = False
        self.calls = []

    def run(self, args, validate=True):
        from ai_sre_agent.kube import validate_args
        validate_args(args)
        self.calls.append(args)
        return 0, "NAME  READY  STATUS  RESTARTS\ncheckout-x  0/1  CrashLoopBackOff  4 (OOMKilled)"

    def get_json(self, args):
        if args[:2] == ["get", "applications.argoproj.io"]:
            return {"items": [{"metadata": {"name": "shop"},
                               "spec": {"destination": {"namespace": "shop"}},
                               "status": {"sync": {"status": "Synced", "revision": "mergesha"},
                                          "health": {"status": "Healthy" if self.healthy else "Degraded"}}}]}
        if args[:2] == ["get", "deployment"]:
            avail = 2 if self.healthy else 1
            return {"metadata": {"generation": 3}, "spec": {"replicas": 2},
                    "status": {"observedGeneration": 3, "updatedReplicas": avail, "availableReplicas": avail}}
        return None


class FakeGrafana:
    def __init__(self):
        self.firing = True

    def promql(self, q, range_minutes=None):
        return {"status": "success", "data": {"resultType": "vector", "result": [
            {"metric": {"container": "checkout"}, "value": [0, "6.5e7"]}]}}

    def active_alerts(self):
        return [{"labels": ALERT["labels"], "state": "Alerting"}] if self.firing else []

    def active_alerts_for(self, ns, wl):
        return self.active_alerts()


@dataclass
class Block:
    type: str
    id: str = ""
    name: str = ""
    input: dict | None = None
    text: str = ""


class FakeAnthropic:
    """Replays a scripted conversation: a list of lists of tool calls."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=self.messages)

    def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})  # snapshot
        calls = self.script.pop(0)
        content = [Block(type="tool_use", id=f"tu_{len(self.requests)}_{i}", name=n, input=inp)
                   for i, (n, inp) in enumerate(calls)]
        return SimpleNamespace(content=content, usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
                               stop_reason="tool_use")


def good_submit(content=FIXED_DEPLOY):
    return ("submit_diagnosis", {
        "summary": "checkout is OOMKilled because its memory limit was cut to 64Mi.",
        "root_cause": "Commit abc123 lowered limits.memory from 256Mi to 64Mi; the app needs ~110MB.",
        "evidence": ["pods show OOMKilled", "commit abc123 changed the limit"],
        "confidence": "high", "action": "pull_request",
        "pr_title": "Restore checkout memory limit to 256Mi",
        "changes": [{"path": "06-demo-app/manifests/deployment.yaml", "content": content}],
        "risk": "Low", "rollback_plan": "Revert the PR", "verification_plan": "OOM alert clears",
        "offending_commit": "abc123def456",
    })
