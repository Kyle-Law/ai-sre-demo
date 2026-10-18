"""CLI entry point. The agent runs in the cluster (step 12); kubectl exec into the controller
for the inspection commands.

    ai-sre-agent operator          # the controller: AgentSession per ticket (the Deployment runs this)
    ai-sre-agent investigate       # one diagnosis, run by the controller as a Job; prints the Diagnosis
    ai-sre-agent diagnose INC-1    # investigate one ticket in a Job, print findings, write nothing
    ai-sre-agent status            # incidents and their timelines
    ai-sre-agent report [--detail] # timing table across incidents (+ how each was found)
    ai-sre-agent selftest          # connectivity + RBAC matrix (outside the cluster: external services only)
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time

from . import formatting as fmt
from .audit import AuditLog
from .config import Config
from .diagnose import Diagnoser
from .github import GitHub, auth_from_config
from .grafana import Grafana
from .jira import Jira
from .incluster import CRStateStore, JobDiagnoser, operator_settings
from .kube import Kubectl, in_cluster
from .workflow import Agent

log = logging.getLogger("ai_sre_agent")


def build(cfg: Config, dry_run: bool | None = None) -> Agent:
    dry = cfg.dry_run if dry_run is None else dry_run
    audit = AuditLog(cfg.audit_log)
    grafana = Grafana(cfg.grafana_url, cfg.grafana_token, cfg.grafana_prom_uid)
    github = GitHub(cfg.github_api_url, auth_from_config(cfg), cfg.github_repo, cfg.github_base_branch, audit, dry)
    jira = Jira(cfg.jira_base_url, cfg.jira_email, cfg.jira_api_token, cfg.jira_project_key, audit, dry,
                api_url=cfg.jira_api_url)
    s = operator_settings()
    diagnoser = JobDiagnoser(cfg, audit, s["job_namespace"], s["image"], s["service_account"])
    return Agent(cfg, jira, github, Kubectl(cfg.kubectl_bin), grafana, diagnoser,
                 CRStateStore(s["session_namespace"]), audit)


def cmd_investigate(cfg: Config) -> None:
    """One diagnosis, read-only, result on stdout for the controller (incluster.JobDiagnoser)."""
    import os
    from .incluster import RESULT_MARKER
    audit = AuditLog(cfg.audit_log)
    github = GitHub(cfg.github_api_url, "", cfg.github_repo, cfg.github_base_branch, audit, dry_run=True)
    diagnoser = Diagnoser(cfg, Kubectl(cfg.kubectl_bin),
                          Grafana(cfg.grafana_url, cfg.grafana_token, cfg.grafana_prom_uid), github, audit)
    diag = diagnoser.run(os.environ["AGENT_TICKET"], os.environ["AGENT_CONTEXT"])
    print(RESULT_MARKER + json.dumps(diag.__dict__, default=str), flush=True)


def cmd_operator(cfg: Config) -> None:
    agent = build(cfg)  # one controller: the Deployment runs replicas: 1
    stop = {"flag": False}

    def _stop(signum, _frame):
        log.info("received signal %s, stopping after this cycle", signum)
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("AI SRE agent started: project=%s repo=%s model=%s dry_run=%s",
             cfg.jira_project_key, cfg.github_repo, cfg.model, cfg.dry_run)
    agent.audit.write("agent_started", model=cfg.model, repo=cfg.github_repo, dry_run=cfg.dry_run)
    log.info("watching Jira project %s for open tickets labelled '%s' every %ss",
             cfg.jira_project_key, cfg.jira_triage_label, cfg.poll_seconds)
    agent.recover()
    heartbeat_every = max(1, 300 // max(cfg.poll_seconds, 1))  # ~5 minutes
    ticks = 0
    while not stop["flag"]:
        agent.tick()
        ticks += 1
        if ticks % heartbeat_every == 0:
            log.info("still watching (%d AgentSession(s))", len(agent.state.all()))
        for _ in range(cfg.poll_seconds):
            if stop["flag"]:
                break
            time.sleep(1)
    agent.audit.write("agent_stopped")


def cmd_diagnose(cfg: Config, key: str) -> None:
    agent = build(cfg, dry_run=True)
    issue = agent.jira.get_issue(key)
    alerts = agent.jira.extract_alerts(issue)
    diag = agent.diagnoser.run(key, agent.build_context(key, issue, alerts, 1, None))
    print(fmt.findings_comment(diag))
    if diag.action == "pull_request":
        print("\n" + fmt.pr_body(key, agent.jira.browse_url(key), diag))
    else:
        print("\n" + fmt.escalation_comment(diag))


def open_store() -> CRStateStore:
    return CRStateStore(operator_settings()["session_namespace"])


OUTCOME = {"VERIFIED": "fixed by agent PR", "RESOLVED": "fixed by human (escalated)",
           "ESCALATED": "escalated, open", "PR_OPEN": "PR awaiting review", "MERGED": "merged, syncing",
           "SYNCED": "verifying", "DIAGNOSING": "diagnosing", "FAILED": "agent error"}


def _ticket_number(row: dict) -> tuple:
    key = row.get("key", "")
    return (key.rsplit("-", 1)[0], int(key.rsplit("-", 1)[-1])) if key.rsplit("-", 1)[-1].isdigit() else (key, 0)


def cmd_report(detail: bool = False) -> None:
    rows = sorted(open_store().all(), key=_ticket_number)
    if not rows:
        print("No incidents handled yet.")
        return
    d = fmt._dur
    header = (f"{'Ticket':8} {'Alert':26} {'Outcome':27} {'Alert->PR/esc':>13} {'Review':>9} "
              f"{'Merge->ok':>9} {'MTTR':>9} {'Automated':>9} {'Human':>9}")
    print(header + "\n" + "-" * len(header))
    done = []
    for r in rows:
        start = r.get("detected_at") or r.get("ticket_created_at")
        t = fmt.timing_totals(r)
        alert = ",".join(r.get("alertnames") or []) or "-"
        print(f"{r['key']:8} {alert[:26]:26} {OUTCOME.get(r.get('stage'), r.get('stage', '?')):27} "
              f"{d(fmt._seconds(start, r.get('pr_opened_at') or r.get('escalated_at'))):>13} "
              f"{d(fmt._seconds(r.get('pr_opened_at'), r.get('merged_at'))):>9} "
              f"{d(fmt._seconds(r.get('merged_at'), r.get('verified_at'))):>9} "
              f"{d(t['mttr']):>9} {d(t['automated'] if t['mttr'] is not None else None):>9} "
              f"{d(t['human'] if t['mttr'] is not None else None):>9}")
        if t["mttr"] is not None:
            done.append(t)
    if done:
        avg = lambda k: sum(x[k] for x in done) // len(done)
        print(f"\nResolved: {len(done)} of {len(rows)}. Average MTTR {d(avg('mttr'))} "
              f"= automated {d(avg('automated'))} + human {d(avg('human'))}.")
    if not detail:
        return
    for r in rows:
        print(f"\n=== {r['key']}  {OUTCOME.get(r.get('stage'), r.get('stage'))}  "
              f"({r.get('namespace')}/{r.get('workload')}, model {r.get('model', '-')})")
        if r.get("diagnosis"):
            print(f"Diagnosis: {r['diagnosis']}")
        if r.get("reasoning_steps"):
            print("How the agent found it:")
            for i, s in enumerate(r["reasoning_steps"], 1):
                print(f"  {i}. {s}")
        if r.get("investigation"):
            print("Investigation (seconds into diagnosis):")
            print("  " + fmt.investigation_lines(r["investigation"], with_results=False).replace("\n", "\n  "))
        print("Where the time went:")
        for label, secs, who in fmt.phase_rows(r):
            print(f"  {label:34} {d(secs):>9}  {who}")


def cmd_status() -> None:
    rows = open_store().all()
    if not rows:
        print("No incidents handled yet.")
    for r in rows:
        print(f"{r['key']:10} {r['stage']:10} attempt={r.get('attempt', 1)} "
              f"{r.get('namespace')}/{r.get('workload')} pr={r.get('pr_url', '-')}")
        for label, t, d in fmt.timeline_rows(r):
            print(f"    {label:22} {t}  (+{d})")


def cmd_selftest(cfg: Config) -> int:
    audit = AuditLog(cfg.audit_log)
    kube = Kubectl(cfg.kubectl_bin)
    grafana = Grafana(cfg.grafana_url, cfg.grafana_token, cfg.grafana_prom_uid)
    github = GitHub(cfg.github_api_url, auth_from_config(cfg), cfg.github_repo, cfg.github_base_branch,
                    audit, dry_run=True)
    jira = Jira(cfg.jira_base_url, cfg.jira_email, cfg.jira_api_token, cfg.jira_project_key, audit,
                dry_run=True, api_url=cfg.jira_api_url)
    failures = 0

    def check(name: str, fn):
        nonlocal failures
        try:
            detail = fn()
            print(f"  PASS  {name}{(': ' + detail) if detail else ''}")
        except Exception as exc:
            failures += 1
            print(f"  FAIL  {name}: {exc}")

    print("Connectivity")
    check("Grafana / Prometheus query", lambda: str(grafana.promql("up").get("status")))
    check("Grafana alert state", lambda: f"{len(grafana.active_alerts())} active")
    check("Jira identity", lambda: jira.check_identity(cfg.jira_sa_name))
    # A wrong JIRA_BASE_URL can still answer searches with 0 results; the project lookup can't.
    check("Jira project", lambda: f"{cfg.jira_project_key} ({jira.get_project()['name']})")
    check("Jira triage queue", lambda: f"{len(jira.triage_queue(cfg.jira_triage_label))} open")
    check("GitHub repo read", lambda: ", ".join(github.list_dir(cfg.allowed_paths[0].rstrip("/"))[:5]))
    if not in_cluster():
        print("\nKubernetes: checked from inside the cluster (make verify-12 ARGS=--selftest)")
        print(f"\n{'All checks passed.' if not failures else f'{failures} check(s) failed.'}")
        return 1 if failures else 0
    check("Kubernetes API (list pods in shop)", lambda: _expect_ok(kube.run(["get", "pods", "-n", "shop"])))

    print("\nRBAC (expect read allowed, everything else denied)")
    matrix = [
        (["get", "pods"], "shop", True), (["get", "pods/log"], "shop", True),
        (["list", "events"], "shop", True), (["get", "configmaps"], "shop", True),
        (["get", "secrets"], "shop", False), (["delete", "pods"], "shop", False),
        (["patch", "deployments"], "shop", False), (["create", "pods/exec"], "shop", False),
        (["update", "applications.argoproj.io"], cfg.argocd_namespace, False),
        (["get", "configmaps"], "kube-system", False),
    ]
    for (verb, resource), ns, expected in matrix:
        res, _, sub = resource.partition("/")
        args = ["auth", "can-i", verb, res, "-n", ns] + ([f"--subresource={sub}"] if sub else [])
        code, out = kube.run(args)
        allowed = out.strip().splitlines()[0].strip() == "yes" if out.strip() else False
        ok = allowed == expected
        failures += 0 if ok else 1
        print(f"  {'PASS' if ok else 'FAIL'}  can-i {verb:6} {resource:28} -n {ns:12} -> "
              f"{'yes' if allowed else 'no'} (expected {'yes' if expected else 'no'})")
    print(f"\n{'All checks passed.' if not failures else f'{failures} check(s) failed.'}")
    return 1 if failures else 0


def _expect_ok(result: tuple[int, str]) -> str:
    code, out = result
    if code != 0:
        raise RuntimeError(out.strip()[:300])
    return f"{max(len(out.strip().splitlines()) - 1, 0)} pods"


def main() -> None:
    parser = argparse.ArgumentParser(prog="ai-sre-agent")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("operator")
    sub.add_parser("investigate")
    d = sub.add_parser("diagnose")
    d.add_argument("key")
    sub.add_parser("status")
    rp = sub.add_parser("report")
    rp.add_argument("--detail", action="store_true", help="also: how each incident was found, and phase timing")
    sub.add_parser("selftest")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.cmd in ("status", "report"):  # need only the AgentSessions, not every secret
        cmd_status() if args.cmd == "status" else cmd_report(args.detail)
        return
    cfg = Config.from_env()
    try:
        if args.cmd == "operator":
            cmd_operator(cfg)
        elif args.cmd == "investigate":
            cmd_investigate(cfg)
        elif args.cmd == "diagnose":
            cmd_diagnose(cfg, args.key)
        elif args.cmd == "selftest":
            sys.exit(cmd_selftest(cfg))
    except RuntimeError as exc:  # API errors: show the message, not a traceback (-v for details)
        if args.verbose:
            raise
        sys.exit(f"error: {exc}")


if __name__ == "__main__":
    main()
