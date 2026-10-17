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
