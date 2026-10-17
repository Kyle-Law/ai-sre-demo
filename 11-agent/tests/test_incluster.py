"""In-cluster mode against a fake kubectl: AgentSession state store, Job-based diagnosis."""

import json
from types import SimpleNamespace

import pytest

from ai_sre_agent import incluster
from ai_sre_agent.audit import AuditLog
from ai_sre_agent.diagnose import Diagnosis
from ai_sre_agent.state import DIAGNOSING, PR_OPEN


class FakeKubectl:
    """Just enough of kubectl for AgentSessions and Jobs."""

    def __init__(self, job_logs=""):
        self.sessions, self.jobs, self.job_logs, self.calls = {}, {}, job_logs, []

    def __call__(self, *args, stdin=None, check=True):
        self.calls.append(args)
        ok = lambda out="": SimpleNamespace(returncode=0, stdout=out, stderr="")
        a = [x for x in args if x not in ("-n", "ai-sre-agent", "ai-sre")]
        if a[:1] == ["apply"]:
            obj = json.loads(stdin)
            self.sessions.setdefault(obj["metadata"]["name"], {"spec": obj["spec"], "status": {}})
            return ok()
        if a[:2] == ["patch", "agentsession"]:
            self.sessions[a[2]]["status"] = json.loads(a[-1])[0]["value"]
            return ok()
        if a[:2] == ["get", "agentsession"]:
            if a[2] not in self.sessions:
                return SimpleNamespace(returncode=1, stdout="", stderr="Error from server (NotFound)")
            return ok(json.dumps(self.sessions[a[2]]))
        if a[:2] == ["get", "agentsessions"]:
            return ok(json.dumps({"items": list(self.sessions.values())}))
        if a[:1] == ["create"]:
            job = json.loads(stdin)
            self.jobs[job["metadata"]["name"]] = job
            return ok()
        if a[:2] == ["get", "job"]:
            return ok(json.dumps({"status": {"succeeded": 1}}))
        if a[:1] == ["logs"]:
            return ok(self.job_logs)
        raise AssertionError(f"unexpected kubectl {args}")


@pytest.fixture()
def fake(monkeypatch):
    k = FakeKubectl()
    monkeypatch.setattr(incluster, "kubectl", k)
    return k


def test_session_store_matches_statestore_semantics(fake):
    store = incluster.CRStateStore("ai-sre-agent")
    assert store.get("SUP-1") is None
    store.put("SUP-1", DIAGNOSING, {"attempt": 1, "first_clear_at": None})
    assert "sup-1" in fake.sessions                       # DNS-safe resource name
    st = store.update("SUP-1", stage=PR_OPEN, pr_number=7)
    assert st["stage"] == PR_OPEN and st["attempt"] == 1 and st["pr_number"] == 7
    assert store.get("SUP-1")["key"] == "SUP-1"           # ticket key comes back from spec
    assert [r["key"] for r in store.in_stage(PR_OPEN)] == ["SUP-1"]
    assert store.in_stage(DIAGNOSING) == []
    assert "first_clear_at" not in fake.sessions["sup-1"]["status"]   # None clears the field


def cfg():
    return SimpleNamespace(model="m", max_turns=30, allowed_paths=["06-demo-app/manifests/"], argocd_namespace="argocd",
                           github_repo="o/r", github_base_branch="main", grafana_url="http://g", grafana_prom_uid="p")


def test_job_is_read_only_and_survives_a_cordoned_node(fake, tmp_path):
    job = incluster.JobDiagnoser(cfg(), AuditLog(str(tmp_path / "a")), "ai-sre", "ai-sre-agent:dev",
                                 "ai-sre-agent").job_manifest("diagnose-sup-1-1", "SUP-1", "ctx")
    pod = job["spec"]["template"]["spec"]
    c = pod["containers"][0]
    assert pod["serviceAccountName"] == "ai-sre-agent" and pod["automountServiceAccountToken"] is True
    assert {"key": "node.kubernetes.io/unschedulable", "operator": "Exists", "effect": "NoSchedule"} in pod["tolerations"]
    assert c["envFrom"] == [{"secretRef": {"name": "investigator-credentials"}}]
    names = {e["name"] for e in c["env"]}
    assert not names & {"JIRA_API_TOKEN", "GITHUB_TOKEN", "GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY_PATH"}
    assert {"name": "AGENT_ROLE", "value": "investigator"} in c["env"]


def test_job_result_round_trips_a_full_diagnosis(fake, tmp_path):
    diag = Diagnosis(summary="s", root_cause="r", evidence=["e"], confidence="high", action="pull_request",
                     changes=[{"path": "06-demo-app/manifests/deployment.yaml", "content": "x\n",
                               "original": "y\n", "diff": "-y\n+x\n"}])
    fake.job_logs = "INFO tool_call ...\n" + incluster.RESULT_MARKER + json.dumps(diag.__dict__) + "\n"
    out = incluster.JobDiagnoser(cfg(), AuditLog(str(tmp_path / "a")), "ai-sre", "img", "sa").run("SUP-1", "ctx")
    assert out == diag                                    # content survives, so the controller can open the PR


def test_job_without_result_fails_loudly(fake, tmp_path):
    fake.job_logs = "Traceback: boom\n"
    with pytest.raises(RuntimeError, match="(?s)produced no diagnosis.*boom"):
        incluster.JobDiagnoser(cfg(), AuditLog(str(tmp_path / "a")), "ai-sre", "img", "sa").run("SUP-1", "ctx")
