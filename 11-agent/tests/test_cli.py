"""CLI-level behaviour: timeline formatting and the single-instance guard."""

import pytest

from ai_sre_agent.__main__ import single_instance
from ai_sre_agent.formatting import timeline_rows


def test_timeline_is_utc_whatever_offset_the_source_uses():
    rows = dict((label, t) for label, t, _ in timeline_rows({
        "detected_at": "2026-10-17T17:08:00Z",
        "ticket_created_at": "2026-10-18T01:08:12.000+0800",   # Jira's format
    }))
    assert rows["Ticket created"] == "2026-10-17 17:08:12"


def test_second_local_agent_is_refused(tmp_path):
    first = single_instance(str(tmp_path / "state.db"))
    with pytest.raises(SystemExit, match="Another agent is already running"):
        single_instance(str(tmp_path / "state.db"))
    first.close()
    single_instance(str(tmp_path / "state.db")).close()      # free again once the first one exits


VERIFIED_INCIDENT = {
    "key": "SUP-3", "stage": "VERIFIED", "alertnames": ["DeploymentRolloutStuck"],
    "detected_at": "2026-10-17T18:40:00Z", "ticket_created_at": "2026-10-17T18:40:16Z",
    "picked_at": "2026-10-17T18:40:22Z", "diagnosed_at": "2026-10-17T18:40:41Z",
    "pr_opened_at": "2026-10-17T18:40:49Z", "merged_at": "2026-10-17T18:46:08Z",
    "synced_at": "2026-10-17T18:46:35Z", "verified_at": "2026-10-17T18:48:13Z",
}


def test_phase_timing_splits_automated_and_human_time():
    from ai_sre_agent import formatting as fmt
    rows = fmt.phase_rows(VERIFIED_INCIDENT)
    assert [r[0] for r in rows] == ["Alert -> ticket", "Ticket -> agent pickup", "Diagnosis", "Diagnosis -> PR opened",
                                    "Review and merge", "Merge -> ArgoCD sync", "Sync -> verified"]
    assert dict((label, secs) for label, secs, _ in rows)["Review and merge"] == 319
    t = fmt.timing_totals(VERIFIED_INCIDENT)
    assert t == {"mttr": 493, "human": 319, "automated": 174}           # 8m13s = 2m54s + 5m19s
    assert "|*MTTR (alert -> resolved)*|*8m 13s*|" in fmt.timing_section(VERIFIED_INCIDENT)


def test_report_table_and_detail(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    from ai_sre_agent import __main__ as cli
    rows = [dict(VERIFIED_INCIDENT, reasoning_steps=["probe on 8080", "app listens on 9898"],
                 investigation=[{"cmd": "kubectl get pods -n shop", "t": 2}])]
    monkeypatch.setattr(cli, "open_store", lambda cfg: SimpleNamespace(all=lambda: rows))
    cli.cmd_report(None, detail=True)
    out = capsys.readouterr().out
    assert "SUP-3" in out and "fixed by agent PR" in out and "8m 13s" in out
    assert "Average MTTR 8m 13s = automated 2m 54s + human 5m 19s" in out
    assert "1. probe on 8080" in out and "+  2s  kubectl get pods -n shop" in out
