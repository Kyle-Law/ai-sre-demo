"""End-to-end lifecycle against fakes: ticket -> diagnosis -> PR -> merge -> sync -> verified."""

from types import SimpleNamespace

import pytest

from ai_sre_agent.audit import AuditLog
from ai_sre_agent.diagnose import Diagnoser
from ai_sre_agent.state import ESCALATED, MERGED, PR_OPEN, SYNCED, VERIFIED, StateStore
from ai_sre_agent.workflow import Agent

from fakes import (BASE_DEPLOY, FakeAnthropic, FakeGitHub, FakeGrafana, FakeJira, FakeKube,
                   good_submit)


def make_cfg(tmp_path, **over):
    base = dict(model="test-model", max_turns=8, argocd_namespace="argocd", allowed_paths=["06-demo-app/manifests/"],
                jira_triage_label="ai-triage", jira_transition_start="In Progress",
                jira_transition_review="In Review", jira_transition_done="Done",
                github_repo="org/repo", github_base_branch="main", github_reviewers=[],
                verify_stable_seconds=0, verify_timeout_seconds=900, sync_timeout_seconds=600,
                max_attempts=2, state_db=str(tmp_path / "s.db"), audit_log=str(tmp_path / "a.jsonl"))
    base.update(over)
    return SimpleNamespace(**base)


def make_agent(tmp_path, script, **cfg_over):
    cfg = make_cfg(tmp_path, **cfg_over)
    audit = AuditLog(cfg.audit_log)
    jira, gh, kube, graf = FakeJira(), FakeGitHub(), FakeKube(), FakeGrafana()
    llm = FakeAnthropic(script)
    diag = Diagnoser(cfg, kube, graf, gh, audit, client=llm)
    agent = Agent(cfg, jira, gh, kube, graf, diag, StateStore(cfg.state_db), audit)
    return agent, jira, gh, kube, graf, llm


def test_full_lifecycle(tmp_path):
    script = [
        [("kubectl", {"args": ["get", "pods", "-n", "shop"]})],
        [("recent_commits", {"path": "06-demo-app/manifests"}), ("commit_diff", {"sha": "abc123def456"})],
        [("read_repo_file", {"path": "06-demo-app/manifests/deployment.yaml"})],
        [good_submit()],
    ]
    agent, jira, gh, kube, graf, llm = make_agent(tmp_path, script)

    agent.tick()  # picks up ticket, diagnoses, opens PR
    st = agent.state.get("INC-1")
    assert st["stage"] == PR_OPEN
    assert gh.opened[0]["title"] == "[INC-1] Restore checkout memory limit to 256Mi"
    assert set(gh.opened[0]["files"]) == {"06-demo-app/manifests/deployment.yaml", "incidents/INC-1.md"}
    assert "memory: 256Mi" in gh.opened[0]["files"]["06-demo-app/manifests/deployment.yaml"]
    assert any("Diagnosis" in c for c in jira.comments["INC-1"])
    assert any("Remediation PR opened" in c for c in jira.comments["INC-1"])
    assert ("INC-1", "In Progress") in jira.transitions

    agent.tick()  # nothing merged yet: no change, ticket not re-processed
    assert agent.state.get("INC-1")["stage"] == PR_OPEN
    assert len(gh.opened) == 1

    gh.reviews[1] = [{"id": 7, "state": "APPROVED", "user": {"login": "alice"}, "body": "LGTM"}]
    gh.prs[1].update(merged=True, state="closed", merged_at="2026-10-17T06:10:00Z",
                     merged_by={"login": "alice"}, merge_commit_sha="mergesha")
    agent.tick()  # sees review + merge, then ArgoCD synced in the same tick
    assert agent.state.get("INC-1")["stage"] == SYNCED
    assert any("approved by *alice*" in c for c in jira.comments["INC-1"])
    assert any("merged* by *alice*" in c for c in jira.comments["INC-1"])

    agent.tick()  # still firing -> not verified
    assert agent.state.get("INC-1")["stage"] == SYNCED

    graf.firing, kube.healthy = False, True
    agent.tick()  # first clear observation
    agent.tick()  # stable window (0s in test) -> verified
    st = agent.state.get("INC-1")
    assert st["stage"] == VERIFIED
    final = jira.comments["INC-1"][-1]
    assert "Incident verified resolved" in final and "MTTR" in final
    assert ("INC-1", "Done") in jira.transitions


def test_invalid_change_is_bounced_back_to_model(tmp_path):
    bad = ("submit_diagnosis", {**good_submit()[1], "changes": [
        {"path": "09-agent-access/manifests/rbac.yaml", "content": "kind: ClusterRole\n"}]})
    script = [[bad], [good_submit()]]
    agent, jira, gh, *_ , llm = make_agent(tmp_path, script)
    agent.tick()
    assert agent.state.get("INC-1")["stage"] == PR_OPEN
    # second request carried the rejection back as an error tool_result
    last_user = llm.requests[1]["messages"][-1]["content"][0]
    assert last_user["is_error"] and "outside allowed paths" in last_user["content"]


def test_forbidden_kind_rejected(tmp_path):
    content = BASE_DEPLOY + "---\napiVersion: v1\nkind: Secret\nmetadata:\n  name: x\n"
    agent, *_ = make_agent(tmp_path, [])
    changes, problems = agent.diagnoser.validate_changes([{"path": "06-demo-app/manifests/deployment.yaml", "content": content}])
    assert not changes and "Secret" in problems[0]


def test_escalation_path(tmp_path):
    script = [[("submit_diagnosis", {
        "summary": "Node is cordoned", "root_cause": "node spec.unschedulable=true",
        "evidence": ["kubectl get nodes shows SchedulingDisabled"], "confidence": "high",
        "action": "escalate", "escalation_reason": "Not fixable in git",
        "next_steps": ["kubectl uncordon <node>"]})]]
    agent, jira, gh, *_ = make_agent(tmp_path, script)
    agent.tick()
    assert agent.state.get("INC-1")["stage"] == ESCALATED
    assert "needs-human" in jira.labels["INC-1"]
    assert not gh.opened


def test_pr_closed_without_merge_escalates(tmp_path):
    agent, jira, gh, *_ = make_agent(tmp_path, [[good_submit()]])
    agent.tick()
    gh.prs[1].update(state="closed", merged=False)
    agent.tick()
    assert agent.state.get("INC-1")["stage"] == ESCALATED


def test_refused_kubectl_is_reported_not_executed(tmp_path):
    script = [[("kubectl", {"args": ["delete", "pod", "checkout-x", "-n", "shop"]})], [good_submit()]]
    agent, jira, gh, kube, graf, llm = make_agent(tmp_path, script)
    agent.tick()
    assert not any(c[0] == "delete" for c in kube.calls)
    result = llm.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] and "REFUSED" in result["content"]


def test_retry_after_failed_verification(tmp_path):
    script = [[good_submit()], [good_submit(BASE_DEPLOY.replace("64Mi", "512Mi"))]]
    agent, jira, gh, kube, graf, llm = make_agent(tmp_path, script, verify_timeout_seconds=0)
    agent.tick()
    gh.prs[1].update(merged=True, state="closed", merged_at="2026-10-17T06:10:00Z",
                     merged_by={"login": "alice"}, merge_commit_sha="mergesha")
    agent.tick()  # merged -> synced
    agent.tick()  # still failing and timeout=0 -> attempt 2 -> new PR
    st = agent.state.get("INC-1")
    assert st["attempt"] == 2 and st["stage"] == PR_OPEN and len(gh.opened) == 2
    assert gh.opened[1]["branch"].endswith("attempt-2")


def test_turn_budget_never_forces_a_tool(tmp_path):
    """Current models reject tool_choice type "tool"; near the budget the agent asks instead."""
    script = [[("kubectl", {"args": ["get", "pods", "-n", "shop"]})]] * 4
    agent, *_, llm = make_agent(tmp_path, script, max_turns=4)
    diag = agent.diagnoser.run("INC-9", "context")
    assert diag.action == "escalate" and diag.escalation_reason == "turn budget exhausted"
    assert all(r["tool_choice"] == {"type": "auto"} for r in llm.requests)
    last_user = llm.requests[2]["messages"][-1]["content"]
    assert any(b.get("type") == "text" and "submit_diagnosis now" in b["text"] for b in last_user)
    assert all(r["cache_control"] == {"type": "ephemeral"} for r in llm.requests)


def test_model_usage_is_audited(tmp_path):
    script = [[("kubectl", {"args": ["get", "pods", "-n", "shop"]})], [good_submit()]]
    agent, *_ = make_agent(tmp_path, script)
    agent.diagnoser.run("INC-7", "context")
    import json
    usage = [json.loads(l) for l in open(tmp_path / "a.jsonl") if '"model_usage"' in l]
    assert usage and usage[0]["model"] == "test-model" and usage[0]["output_tokens"] == 400 and usage[0]["turns"] == 2
