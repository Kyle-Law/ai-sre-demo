"""Jira (wiki markup) comments, PR body and the in-repo incident record."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .diagnose import Diagnosis
from .state import parse_iso

AGENT_SIG = "_— AI SRE agent (read-only cluster access; changes only via human-approved PRs)_"


def _cmd(call: dict) -> str:
    tool, inp = call["tool"], call["input"]
    if tool == "kubectl":
        return "kubectl " + " ".join(inp.get("args", []))
    if tool == "promql":
        rng = f" [range {inp['range_minutes']}m]" if inp.get("range_minutes") else ""
        return f"promql: {inp.get('query')}{rng}"
    return f"{tool} {json.dumps(inp)}"


def pickup_comment(key: str, alerts: list[dict], attempt: int) -> str:
    names = ", ".join(sorted({a.get("alertname") or a.get("labels", {}).get("alertname", "?") for a in alerts})) or "unknown"
    retry = f" (attempt {attempt})" if attempt > 1 else ""
    return (f"(*) *AI SRE agent picked up this incident{retry}.*\n"
            f"Alerts: {names}\n"
            "Investigating with a read-only kubeconfig, Prometheus metrics and git history. "
            "No changes will be made to the cluster.\n\n" + AGENT_SIG)


def findings_comment(d: Diagnosis) -> str:
    evidence = "\n".join(f"# {e}" for e in d.evidence) or "# (none recorded)"
    commands = "\n".join(_cmd(c) + ("   <- error" if c.get("error") else "") for c in d.investigation)
    lines = [
        "h3. (i) Diagnosis",
        f"*Summary:* {d.summary}",
        f"*Root cause:* {d.root_cause}",
        f"*Confidence:* {d.confidence.upper()}",
    ]
    if d.offending_commit:
        lines.append(f"*Introduced by commit:* {{{{{d.offending_commit}}}}}")
    lines += ["", "*Evidence:*", evidence, "",
              f"*Investigation log* ({len(d.investigation)} read-only calls, {d.turns} model turns, "
              f"model {{{{{d.model}}}}}, {d.input_tokens + d.output_tokens:,} tokens):",
              "{noformat}", commands or "(no tool calls)", "{noformat}"]
    for ch in d.changes:
        lines += ["", f"*Proposed change to* {{{{{ch['path']}}}}}:", "{code:diff}", ch["diff"].rstrip(), "{code}"]
    lines += ["", AGENT_SIG]
    return "\n".join(lines)


def pr_opened_comment(pr: dict, d: Diagnosis) -> str:
    return (f"(/) *Remediation PR opened:* [PR #{pr['number']}|{pr['html_url']}]\n"
            f"*Risk:* {d.risk or '-'}\n*Rollback:* {d.rollback_plan or 'Revert the PR.'}\n"
            f"*Verification plan:* {d.verification_plan or '-'}\n\n"
            "(!) Waiting for a human to review and merge. Nothing has been changed yet.\n\n" + AGENT_SIG)


def escalation_comment(d: Diagnosis, reason: str | None = None) -> str:
    steps = "\n".join(f"# {s}" for s in d.next_steps) or "# Investigate manually using the evidence above."
    return ("h3. (!) Escalating to a human — no PR opened\n"
            f"*Why:* {reason or d.escalation_reason or 'Root cause is not fixable through the GitOps repository.'}\n\n"
            f"*Recommended next steps:*\n{steps}\n\n" + AGENT_SIG)


def review_comment(review: dict, pr_number: int) -> str:
    state = review.get("state", "COMMENTED").replace("_", " ").lower()
    body = (review.get("body") or "").strip()
    quoted = f"\n{{quote}}{body[:2000]}{{quote}}" if body else ""
    return f"(i) PR #{pr_number} {state} by *{review.get('user', {}).get('login', '?')}*{quoted}"


def merged_comment(pr: dict) -> str:
    return (f"(/) *PR #{pr['number']} merged* by *{(pr.get('merged_by') or {}).get('login', '?')}* "
            f"at {pr.get('merged_at')} (merge commit {{{{{(pr.get('merge_commit_sha') or '')[:12]}}}}}).\n"
            "Waiting for ArgoCD to sync the change to the cluster.\n\n" + AGENT_SIG)


def synced_comment(app: str, revision: str, health: str) -> str:
    return (f"(/) *ArgoCD synced* application {{{{{app}}}}} to revision {{{{{revision[:12]}}}}} "
            f"(health: {health}). Verifying that the incident is resolved...\n\n" + AGENT_SIG)


def _fmt(ts: str | None) -> str:
    dt = parse_iso(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "-"


def _delta(start: str | None, end: str | None) -> str:
    a, b = parse_iso(start), parse_iso(end)
    if not a or not b:
        return "-"
    secs = int((b - a).total_seconds())
    return f"{secs // 60}m {secs % 60:02d}s"


TIMELINE_STEPS = [
    ("Alert started firing", "detected_at"),
    ("Ticket created", "ticket_created_at"),
    ("Agent picked up", "picked_at"),
    ("Diagnosis complete", "diagnosed_at"),
    ("PR opened", "pr_opened_at"),
    ("PR merged (human)", "merged_at"),
    ("ArgoCD synced", "synced_at"),
    ("Verified resolved", "verified_at"),
]


def timeline_rows(state: dict) -> list[tuple[str, str, str]]:
    start = state.get("detected_at") or state.get("ticket_created_at")
    return [(label, _fmt(state.get(field)), _delta(start, state.get(field)))
            for label, field in TIMELINE_STEPS if state.get(field)]


def verified_comment(state: dict, checks: list[str]) -> str:
    rows = "\n".join(f"|{l}|{t}|{d}|" for l, t, d in timeline_rows(state))
    mttr = _delta(state.get("detected_at") or state.get("ticket_created_at"), state.get("verified_at"))
    human_wait = _delta(state.get("pr_opened_at"), state.get("merged_at"))
    check_lines = "\n".join(f"* (/) {c}" for c in checks)
    return ("h3. (/) Incident verified resolved\n"
            f"{check_lines}\n\n"
            "h4. Timeline (UTC)\n"
            "||Step||Time||Since detection||\n"
            f"{rows}\n\n"
            f"*MTTR:* {mttr}   |   *Time waiting for human review:* {human_wait}\n\n"
            "Full audit trail: this ticket, the PR, git history, ArgoCD sync history and the agent audit log.\n\n"
            + AGENT_SIG)


def pr_body(key: str, jira_url: str, d: Diagnosis) -> str:
    evidence = "\n".join(f"- {e}" for e in d.evidence)
    commands = "\n".join(_cmd(c) for c in d.investigation)
    offending = f"\nIntroduced by commit `{d.offending_commit}`." if d.offending_commit else ""
    return f"""## 🤖 AI SRE remediation for [{key}]({jira_url})

> **This PR was generated by an AI agent.** The agent has *read-only* access to the
> cluster and cannot merge. Nothing changes until a human approves and merges;
> ArgoCD then applies it.

### Summary
{d.summary}

### Root cause
{d.root_cause}
{offending}

### Evidence
{evidence}

### Risk
{d.risk or "-"}

### Rollback
{d.rollback_plan or "Revert this PR; ArgoCD will roll back automatically."}

### How the agent will verify
{d.verification_plan or "Alert resolves, all replicas available, ArgoCD Synced/Healthy."}
After merge the agent watches ArgoCD sync and the alert state, then reports back on the Jira ticket.

<details><summary>Investigation log ({len(d.investigation)} read-only calls · confidence: {d.confidence})</summary>

```
{commands}
```
</details>

---
Reviewer checklist: [ ] root cause makes sense · [ ] change is minimal · [ ] rollback is clear
"""


def incident_record(key: str, jira_url: str, alerts: list[dict], d: Diagnosis) -> str:
    """Markdown file committed in the PR under incidents/ so git holds the incident history."""
    alert_lines = "\n".join(
        f"- `{a.get('alertname') or a.get('labels', {}).get('alertname')}` "
        f"{a.get('labels', {}).get('namespace', '')}/{a.get('labels', {}).get('workload', '')} "
        f"since {a.get('startsAt', '-')}" for a in alerts) or "- (none parsed)"
    files = "\n".join(f"- `{c['path']}`" for c in d.changes)
    evidence = "\n".join(f"- {e}" for e in d.evidence)
    return f"""# Incident {key}

- Ticket: {jira_url}
- Recorded: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC
- Diagnosed by: AI SRE agent (`{d.model}`), confidence **{d.confidence}**

## Alerts
{alert_lines}

## Summary
{d.summary}

## Root cause
{d.root_cause}

## Evidence
{evidence}

## Remediation (this PR)
{files}

Risk: {d.risk or '-'}

Rollback: {d.rollback_plan or 'Revert the PR.'}
"""
