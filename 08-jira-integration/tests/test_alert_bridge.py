"""Alert bridge against an in-process fake Jira (create / dedupe / correlate / resolve)."""

import importlib.util
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

BRIDGE = Path(__file__).resolve().parents[1] / "manifests/bridge.py"


class FakeJiraState:
    def __init__(self):
        self.issues = {}  # key -> {"labels": [...], "comments": [...], "fields": {...}}


def make_handler(state):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, code, body):
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _body(self):
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/rest/api/3/search/jql":
                jql = parse_qs(u.query)["jql"][0]
                label = re.search(r'labels = "([^"]+)"', jql).group(1)
                hits = [{"key": k, "fields": {"labels": v["labels"]}} for k, v in state.issues.items()
                        if label in v["labels"] and not v.get("done")]
                return self._json(200, {"issues": hits, "isLast": True})
            self._json(404, {})

        def do_POST(self):
            body = self._body()
            if self.path == "/rest/api/2/issue":
                key = f"INC-{len(state.issues) + 1}"
                state.issues[key] = {"labels": body["fields"]["labels"], "comments": [], "fields": body["fields"]}
                return self._json(201, {"key": key})
            m = re.match(r"/rest/api/2/issue/([A-Z]+-\d+)/comment", self.path)
            if m:
                state.issues[m.group(1)]["comments"].append(body["body"])
                return self._json(201, {})
            self._json(404, {})

        def do_PUT(self):
            body = self._body()
            m = re.match(r"/rest/api/2/issue/([A-Z]+-\d+)$", self.path)
            if m:
                for op in body["update"]["labels"]:
                    state.issues[m.group(1)]["labels"].append(op["add"])
                self.send_response(204)
                self.end_headers()
                return
            self._json(404, {})
    return H


@pytest.fixture()
def bridge():
    state = FakeJiraState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ.update(JIRA_BASE_URL=f"http://127.0.0.1:{server.server_port}", JIRA_EMAIL="bot@x",
                      JIRA_API_TOKEN="t", JIRA_PROJECT_KEY="INC", DRY_RUN="false")
    spec = importlib.util.spec_from_file_location("bridge", BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    jira = mod.Jira(mod.JIRA_BASE_URL, "bot@x", "t")
    yield mod, jira, state
    server.shutdown()


def alert(name, status="firing", fp="aaa111", workload="checkout"):
    return {"status": status, "fingerprint": fp, "startsAt": "2026-10-17T06:00:00Z",
            "endsAt": "2026-10-17T06:20:00Z", "generatorURL": "http://grafana/alerting/x",
            "labels": {"alertname": name, "namespace": "shop", "workload": workload,
                       "severity": "critical", "ai_triage": "true"},
            "annotations": {"summary": f"shop/{workload} {name}"}}


def test_create_dedupe_correlate_resolve(bridge):
    mod, jira, state = bridge
    r = mod.process_payload(jira, {"alerts": [alert("ContainerOOMKilled")]})
    assert r[0]["action"] == "created" and r[0]["key"] == "INC-1"
    issue = state.issues["INC-1"]
    assert "ai-triage" in issue["labels"] and "wl-shop-checkout" in issue["labels"]
    assert "ALERT_JSON_BEGIN" in issue["fields"]["description"]
    assert issue["fields"]["summary"] == "[CRITICAL] ContainerOOMKilled: shop/checkout"

    # Grafana repeat notification for the same alert -> no new ticket
    r = mod.process_payload(jira, {"alerts": [alert("ContainerOOMKilled")]})
    assert r[0]["action"] == "noop" and len(state.issues) == 1

    # Different alert, same workload -> correlated onto INC-1
    r = mod.process_payload(jira, {"alerts": [alert("DeploymentRolloutStuck", fp="bbb222")]})
    assert r[0]["action"] == "correlated" and r[0]["key"] == "INC-1"
    assert "fp-bbb222" in state.issues["INC-1"]["labels"]
    assert "Correlated alert" in state.issues["INC-1"]["comments"][-1]

    # Other workload -> its own ticket
    r = mod.process_payload(jira, {"alerts": [alert("PodUnschedulable", fp="ccc333", workload="cart")]})
    assert r[0]["key"] == "INC-2"

    # Resolution -> comment on INC-1
    r = mod.process_payload(jira, {"alerts": [alert("ContainerOOMKilled", status="resolved")]})
    assert r[0]["keys"] == ["INC-1"] and "RESOLVED" in state.issues["INC-1"]["comments"][-1]


def test_non_triage_alerts_ignored(bridge):
    mod, jira, state = bridge
    a = alert("Watchdog")
    a["labels"]["ai_triage"] = "false"
    r = mod.process_payload(jira, {"alerts": [a]})
    assert r[0]["skipped"] and not state.issues


def test_agent_parses_bridge_description(bridge):
    """The agent's ALERT_JSON parser must understand what the bridge writes."""
    import sys
    sys.path.insert(0, str(BRIDGE.parents[2] / "11-agent"))
    from ai_sre_agent.jira import Jira as AgentJira
    mod, jira, state = bridge
    mod.process_payload(jira, {"alerts": [alert("ContainerOOMKilled")]})
    mod.process_payload(jira, {"alerts": [alert("DeploymentRolloutStuck", fp="bbb222")]})
    issue = state.issues["INC-1"]
    fake = {"fields": {"description": issue["fields"]["description"],
                       "comment": {"comments": [{"body": c} for c in issue["comments"]]}}}
    alerts = AgentJira.extract_alerts(fake)
    assert [a["alertname"] for a in alerts] == ["ContainerOOMKilled", "DeploymentRolloutStuck"]
    assert alerts[0]["labels"]["workload"] == "checkout"


def test_auth_header_user_token_vs_service_account(bridge):
    mod, _, _ = bridge
    assert mod.Jira("u", "bot@x", "t").headers["Authorization"].startswith("Basic ")
    assert mod.Jira("u", "", "ATSTT-scoped").headers["Authorization"] == "Bearer ATSTT-scoped"
