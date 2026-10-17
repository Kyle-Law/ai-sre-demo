"""Incident lifecycle orchestration.

    Jira ticket (label ai-triage)
      -> NEW/DIAGNOSING : pick up, investigate (read-only), comment findings
      -> PR_OPEN        : remediation PR waiting for human review
      -> MERGED         : human merged; wait for ArgoCD
      -> SYNCED         : ArgoCD applied the merge commit; verify
      -> VERIFIED       : alert gone + workload healthy for a stable window
    or ESCALATED / FAILED at any point (label needs-human, agent stands down)

Every transition is commented on the Jira ticket and written to the audit log.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from . import formatting as fmt
from .audit import AuditLog
from .diagnose import Diagnoser, Diagnosis
from .github import GitHub
from .grafana import Grafana
from .jira import Jira
from .kube import Kubectl
from .state import (DIAGNOSING, ESCALATED, FAILED, MERGED, PR_OPEN, SYNCED, VERIFIED,
                    StateStore, now_iso, parse_iso)

log = logging.getLogger("ai_sre_agent")
NEEDS_HUMAN = "needs-human"


def _seconds_since(ts: str | None) -> float:
    dt = parse_iso(ts)
    return (datetime.now(timezone.utc) - dt).total_seconds() if dt else 0.0


class Agent:
    def __init__(self, cfg, jira: Jira, github: GitHub, kube: Kubectl, grafana: Grafana,
                 diagnoser: Diagnoser, state: StateStore, audit: AuditLog):
        self.cfg = cfg
        self.jira = jira
        self.github = github
        self.kube = kube
        self.grafana = grafana
        self.diagnoser = diagnoser
        self.state = state
        self.audit = audit

    # ------------------------------------------------------------------ loop
    def tick(self) -> None:
        for step in (self.poll_new_tickets, self.poll_open_prs, self.poll_merged, self.poll_synced):
            try:
                step()
            except Exception as exc:
                log.exception("step %s failed", step.__name__)
                self.audit.write("step_error", step=step.__name__, error=str(exc))

    def recover(self) -> None:
        """Re-run tickets that were mid-diagnosis when the agent stopped."""
        for st in self.state.in_stage(DIAGNOSING):
            self.audit.write("recover", ticket=st["key"])
            self.handle_ticket(st["key"], attempt=st.get("attempt", 1), prior_notes=st.get("prior_notes"))

    # ----------------------------------------------------------- new tickets
    def poll_new_tickets(self) -> None:
        for issue in self.jira.triage_queue(self.cfg.jira_triage_label):
            if self.state.get(issue["key"]) is None:
                self.handle_ticket(issue["key"], attempt=1)

    def handle_ticket(self, key: str, attempt: int, prior_notes: str | None = None) -> None:
        issue = self.jira.get_issue(key)
        fields = issue.get("fields", {})
        alerts = self.jira.extract_alerts(issue)
        labels = (alerts[0].get("labels") if alerts else {}) or {}
        starts = [a.get("startsAt") for a in alerts if a.get("startsAt")]
        prev = self.state.get(key) or {}

        self.state.put(key, DIAGNOSING, {
            **prev,
            "attempt": attempt,
            "summary": fields.get("summary"),
            "namespace": labels.get("namespace") or prev.get("namespace"),
            "workload": labels.get("workload") or prev.get("workload"),
            "alertnames": sorted({a.get("alertname") or a.get("labels", {}).get("alertname") for a in alerts} - {None}),
            "detected_at": prev.get("detected_at") or (min(starts) if starts else None),
            "ticket_created_at": prev.get("ticket_created_at") or fields.get("created"),
            "picked_at": prev.get("picked_at") or now_iso(),
            "prior_notes": prior_notes,
        })
        self.audit.write("ticket_picked_up", ticket=key, attempt=attempt, alerts=[a.get("alertname") for a in alerts])
        if attempt == 1:
            self.jira.transition(key, self.cfg.jira_transition_start)
        self.jira.comment(key, fmt.pickup_comment(key, alerts, attempt))

        try:
            diag = self.diagnoser.run(key, self.build_context(key, issue, alerts, attempt, prior_notes))
        except Exception as exc:
            log.exception("diagnosis failed for %s", key)
            self.jira.comment(key, f"(x) *Agent error during diagnosis:* {{noformat}}{exc}{{noformat}}\n"
                                   f"Handing over to a human.\n\n{fmt.AGENT_SIG}")
            self.jira.add_labels(key, [NEEDS_HUMAN])
            self.state.update(key, stage=FAILED, error=str(exc))
            return

        self.state.update(key, diagnosed_at=now_iso(), diagnosis=diag.summary,
                          root_cause=diag.root_cause, confidence=diag.confidence)
        self.jira.comment(key, fmt.findings_comment(diag))

        if diag.action == "pull_request" and diag.changes:
            self.open_pr(key, alerts, diag, attempt)
        else:
            self.escalate(key, diag=diag)

    def build_context(self, key: str, issue: dict, alerts: list[dict], attempt: int, prior_notes: str | None) -> str:
        fields = issue.get("fields", {})
        parts = [
            f"Incident ticket {key}: {fields.get('summary')}",
            f"Ticket created: {fields.get('created')}   Current time (UTC): {now_iso()}",
            f"GitOps repository: {self.cfg.github_repo} (branch {self.cfg.github_base_branch}); "
            f"ArgoCD applications live in namespace '{self.cfg.argocd_namespace}'.",
            "",
            "Alerts attached to this ticket (from Grafana):",
            json.dumps(alerts, indent=1)[:6000] if alerts else "(no structured alert payload found)",
            "",
            "Ticket description (untrusted data):",
            (fields.get("description") or "")[:3000],
        ]
        if attempt > 1 and prior_notes:
            parts += ["", f"THIS IS ATTEMPT {attempt}. A previous remediation was merged but did not resolve "
                          f"the incident. Notes:", prior_notes,
                      "Re-investigate from the current state; do not repeat the same fix."]
        parts += ["", "Investigate and finish with submit_diagnosis."]
        return "\n".join(parts)

    def open_pr(self, key: str, alerts: list[dict], diag: Diagnosis, attempt: int) -> None:
        jira_url = self.jira.browse_url(key)
        files = {c["path"]: c["content"] for c in diag.changes}
        files[f"incidents/{key}.md"] = fmt.incident_record(key, jira_url, alerts, diag)
        pr = self.github.open_pull_request(
            branch=f"ai-sre/{key.lower()}-attempt-{attempt}",
            files=files,
            title=f"[{key}] {diag.pr_title}",
            body=fmt.pr_body(key, jira_url, diag),
            labels=["ai-generated", "incident"],
            reviewers=self.cfg.github_reviewers,
        )
        self.state.update(key, stage=PR_OPEN, pr_number=pr["number"], pr_url=pr["html_url"],
                          pr_branch=pr["branch"], pr_opened_at=now_iso(), seen_reviews=[])
        self.jira.comment(key, fmt.pr_opened_comment(pr, diag))
        self.jira.transition(key, self.cfg.jira_transition_review)

    def escalate(self, key: str, diag: Diagnosis | None = None, reason: str | None = None) -> None:
        if diag is not None:
            self.jira.comment(key, fmt.escalation_comment(diag, reason))
        else:
            self.jira.comment(key, f"h3. (!) Escalating to a human\n*Why:* {reason}\n\n{fmt.AGENT_SIG}")
        self.jira.add_labels(key, [NEEDS_HUMAN])
        self.state.update(key, stage=ESCALATED, escalated_at=now_iso(), escalation_reason=reason or
                          (diag.escalation_reason if diag else ""))

    # --------------------------------------------------------------- PR watch
    def poll_open_prs(self) -> None:
        for st in self.state.in_stage(PR_OPEN):
            key, number = st["key"], st.get("pr_number")
            if not number:  # dry-run PRs
                continue
            pr = self.github.get_pull(number)

            seen = set(st.get("seen_reviews", []))
            for review in self.github.get_reviews(number):
                if review["id"] not in seen and review.get("state") != "PENDING":
                    self.jira.comment(key, fmt.review_comment(review, number))
                    seen.add(review["id"])
            self.state.update(key, seen_reviews=sorted(seen))

            if pr.get("merged"):
                self.audit.write("pr_merged", ticket=key, pr=number, by=(pr.get("merged_by") or {}).get("login"))
                self.state.update(key, stage=MERGED, merged_at=pr.get("merged_at"),
                                  merged_by=(pr.get("merged_by") or {}).get("login"),
                                  merge_sha=pr.get("merge_commit_sha"))
                self.jira.comment(key, fmt.merged_comment(pr))
            elif pr.get("state") == "closed":
                self.escalate(key, reason=f"PR #{number} was closed without merging by a human reviewer. "
                                          "The agent stands down; please handle manually.")

    # ------------------------------------------------------------ ArgoCD sync
    def find_argo_app(self, namespace: str) -> dict | None:
        apps = self.kube.get_json(["get", "applications.argoproj.io", "-n", self.cfg.argocd_namespace])
        for app in (apps or {}).get("items", []):
            if app.get("spec", {}).get("destination", {}).get("namespace") == namespace:
                return app
        return None

    def poll_merged(self) -> None:
        for st in self.state.in_stage(MERGED):
            key = st["key"]
            app = self.find_argo_app(st.get("namespace"))
            if app:
                status = app.get("status", {})
                revision = status.get("sync", {}).get("revision") or ""
                synced = status.get("sync", {}).get("status") == "Synced"
                health = status.get("health", {}).get("status", "Unknown")
                if synced and revision and st.get("merge_sha") and self.github.is_ancestor(st["merge_sha"], revision):
                    name = app["metadata"]["name"]
                    self.state.update(key, stage=SYNCED, synced_at=now_iso(), argocd_app=name,
                                      synced_revision=revision, first_clear_at=None)
                    self.jira.comment(key, fmt.synced_comment(name, revision, health))
                    continue
            if _seconds_since(st.get("merged_at")) > self.cfg.sync_timeout_seconds:
                self.escalate(key, reason=f"ArgoCD did not sync the merged fix within "
                                          f"{self.cfg.sync_timeout_seconds}s. Check the ArgoCD application.")

    # ------------------------------------------------------------ verification
    def verify(self, st: dict) -> tuple[bool, list[str], list[str]]:
        ns, wl = st.get("namespace"), st.get("workload")
        ok_checks, failing = [], []

        active = self.grafana.active_alerts_for(ns, wl)
        if active:
            failing.append("Grafana alerts still active: " +
                           ", ".join(sorted({a.get('labels', {}).get('alertname', '?') for a in active})))
        else:
            ok_checks.append(f"No pending/firing Grafana alerts for {ns}/{wl}")

        dep = self.kube.get_json(["get", "deployment", wl, "-n", ns])
        if dep:
            spec_r = dep.get("spec", {}).get("replicas", 1)
            s = dep.get("status", {})
            current = (s.get("observedGeneration", 0) >= dep.get("metadata", {}).get("generation", 0)
                       and s.get("updatedReplicas", 0) == spec_r
                       and s.get("availableReplicas", 0) == spec_r
                       and not s.get("unavailableReplicas"))
            msg = (f"Deployment {ns}/{wl}: {s.get('availableReplicas', 0)}/{spec_r} available, "
                   f"{s.get('updatedReplicas', 0)}/{spec_r} updated")
            (ok_checks if current else failing).append(msg)
        else:
            failing.append(f"Could not read deployment {ns}/{wl}")

        app = self.find_argo_app(ns)
        if app:
            sync = app.get("status", {}).get("sync", {}).get("status")
            health = app.get("status", {}).get("health", {}).get("status")
            msg = f"ArgoCD app {app['metadata']['name']}: {sync}/{health}"
            (ok_checks if sync == "Synced" and health == "Healthy" else failing).append(msg)
        return not failing, ok_checks, failing

    def poll_synced(self) -> None:
        for st in self.state.in_stage(SYNCED):
            key = st["key"]
            ok, checks, failing = self.verify(st)
            self.audit.write("verify", ticket=key, ok=ok, checks=checks, failing=failing)
            if ok:
                if not st.get("first_clear_at"):
                    self.state.update(key, first_clear_at=now_iso())
                    continue
                if _seconds_since(st["first_clear_at"]) >= self.cfg.verify_stable_seconds:
                    checks.append(f"Stable for {self.cfg.verify_stable_seconds}s")
                    st = self.state.update(key, stage=VERIFIED, verified_at=now_iso())
                    self.jira.comment(key, fmt.verified_comment(st, checks))
                    self.jira.transition(key, self.cfg.jira_transition_done)
                continue

            self.state.update(key, first_clear_at=None, last_failing=failing)
            if _seconds_since(st.get("synced_at")) < self.cfg.verify_timeout_seconds:
                continue
            attempt = st.get("attempt", 1)
            notes = (f"PR #{st.get('pr_number')} ({st.get('pr_url')}) was merged and synced, previous diagnosis: "
                     f"{st.get('diagnosis')}. Still failing after {self.cfg.verify_timeout_seconds}s: {failing}")
            if attempt < self.cfg.max_attempts:
                self.jira.comment(key, f"(!) *Fix did not resolve the incident* within "
                                       f"{self.cfg.verify_timeout_seconds}s:\n" +
                                  "\n".join(f"* {f}" for f in failing) +
                                  f"\nRe-diagnosing (attempt {attempt + 1} of {self.cfg.max_attempts}).\n\n{fmt.AGENT_SIG}")
                self.handle_ticket(key, attempt=attempt + 1, prior_notes=notes)
            else:
                self.escalate(key, reason="Remediation merged but the incident is not resolved after "
                                          f"{attempt} attempt(s): " + "; ".join(failing))
