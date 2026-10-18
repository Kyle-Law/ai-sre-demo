"""Jira transitions against a model of the SUP service-desk Task workflow, where Pending has no
direct route to Done (seen live on SUP-3)."""

import json

import pytest

from ai_sre_agent.audit import AuditLog
from ai_sre_agent.jira import Jira

# status -> {transition name: target status}
WORKFLOW = {
    "Open": {"Start progress": "Work in progress", "Pending": "Pending"},
    "Work in progress": {"Back to open": "Open", "Pending": "Pending", "Mark as done": "Done"},
    "Pending": {"Back to open": "Open", "Start progress": "Work in progress"},
    "Done": {"Reopen": "Reopened"},
}


class FakeJiraWorkflow(Jira):
    def __init__(self, tmp_path, status="Open", dry_run=False):
        super().__init__("https://jira.test", "e", "t", "SUP", AuditLog(str(tmp_path / "a.jsonl")), dry_run)
        self.status, self.posts = status, []

    def _req(self, method, path, **kwargs):
        moves = WORKFLOW[self.status]
        ids = {str(i): name for i, name in enumerate(moves)}
        if method == "GET" and path.endswith("/transitions"):
            return {"transitions": [{"id": i, "name": n, "to": {"name": moves[n]}} for i, n in ids.items()]}
        if method == "POST" and path.endswith("/transitions"):
            self.posts.append(ids[json.loads(kwargs["data"])["transition"]["id"]])
            self.status = moves[self.posts[-1]]
            return {}
        if method == "GET":
            return {"fields": {"status": {"name": self.status}}}
        raise AssertionError((method, path))


def test_pickup_to_pending_and_done_via_work_in_progress(tmp_path):
    j = FakeJiraWorkflow(tmp_path, "Open")
    assert j.transition("SUP-9", "Pending")                       # pickup: Open -> Pending directly
    assert j.status == "Pending"
    assert j.transition("SUP-9", "Work in progress > Done")      # resolved: no direct Pending -> Done
    assert j.status == "Done" and j.posts == ["Pending", "Start progress", "Mark as done"]


def test_step_already_reached_is_skipped(tmp_path):
    j = FakeJiraWorkflow(tmp_path, "Work in progress")
    assert j.transition("SUP-9", "Work in progress > Done")
    assert j.posts == ["Mark as done"]


def test_unavailable_step_stops_and_is_audited(tmp_path):
    j = FakeJiraWorkflow(tmp_path, "Pending")
    assert not j.transition("SUP-9", "Done")
    assert j.status == "Pending" and j.posts == []
    events = [json.loads(l) for l in open(tmp_path / "a.jsonl")]
    assert events[-1]["event"] == "jira_transition_unavailable"
    assert events[-1]["available"] == ["Back to open", "Start progress"]


@pytest.mark.parametrize("name", ["", None])
def test_empty_setting_does_nothing(tmp_path, name):
    j = FakeJiraWorkflow(tmp_path, "Pending")
    assert not j.transition("SUP-9", name) and j.posts == []


def test_dry_run_moves_nothing(tmp_path):
    j = FakeJiraWorkflow(tmp_path, "Pending", dry_run=True)
    assert j.transition("SUP-9", "Work in progress > Done") and j.posts == []


def test_service_account_uses_gateway_and_bearer(tmp_path):
    """Scoped tokens only work via api.atlassian.com; ticket links must still point at the site."""
    sent = []
    j = Jira("https://site.atlassian.net", "", "ATSTT-token", "SUP", AuditLog(str(tmp_path / "a")),
             api_url="https://api.atlassian.com/ex/jira/cloud-1")
    j.session.request = lambda method, url, **kw: sent.append((url, j.session.headers.get("Authorization"),
                                                                 j.session.auth)) or type(
        "R", (), {"status_code": 200, "content": b"{}", "json": lambda self: {}})()
    j.get_project()
    assert sent == [("https://api.atlassian.com/ex/jira/cloud-1/rest/api/2/project/SUP", "Bearer ATSTT-token", None)]
    assert j.browse_url("SUP-1") == "https://site.atlassian.net/browse/SUP-1"


def test_user_token_keeps_basic_auth_on_the_site(tmp_path):
    j = Jira("https://site.atlassian.net", "me@example.com", "ATATT-token", "SUP", AuditLog(str(tmp_path / "a")))
    assert j.api_url == "https://site.atlassian.net" and j.session.auth == ("me@example.com", "ATATT-token")
    assert "Authorization" not in j.session.headers


class WhoAmI(Jira):
    def __init__(self, tmp_path, name, account_type="app"):
        super().__init__("https://site", "", "t", "SUP", AuditLog(str(tmp_path / "a")))
        self.me = {"displayName": name, "accountType": account_type}

    def _req(self, method, path, **kwargs):
        assert (method, path) == ("GET", "/rest/api/2/myself")
        return self.me


def test_identity_matches_configured_service_account(tmp_path):
    assert WhoAmI(tmp_path, "sre-bot").check_identity("sre-bot").startswith("sre-bot (accountType app)")


def test_identity_mismatch_fails(tmp_path):
    with pytest.raises(RuntimeError, match="belongs to Kyle .* expected service account 'sre-bot'"):
        WhoAmI(tmp_path, "Kyle", "atlassian").check_identity("sre-bot")


def test_identity_unset_only_reports(tmp_path):
    assert "set the expected" in WhoAmI(tmp_path, "Kyle", "atlassian").check_identity("")
