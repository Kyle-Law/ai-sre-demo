"""CLI entry point.

    python -m ai_sre_agent run              # main loop (11-agent/run.sh runs this)
    python -m ai_sre_agent once             # a single poll cycle
    python -m ai_sre_agent diagnose INC-1   # investigate one ticket, print findings, write nothing
    python -m ai_sre_agent status           # incidents in the local state DB
    python -m ai_sre_agent selftest         # connectivity + proof the kubeconfig is read-only
"""

from __future__ import annotations

import argparse
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
from .kube import Kubectl
from .state import StateStore
from .workflow import Agent

log = logging.getLogger("ai_sre_agent")


def build(cfg: Config, dry_run: bool | None = None) -> Agent:
    dry = cfg.dry_run if dry_run is None else dry_run
    audit = AuditLog(cfg.audit_log)
    kube = Kubectl(cfg.kubeconfig, cfg.kubectl_bin)
    grafana = Grafana(cfg.grafana_url, cfg.grafana_token, cfg.grafana_prom_uid)
    github = GitHub(cfg.github_api_url, auth_from_config(cfg), cfg.github_repo, cfg.github_base_branch, audit, dry)
    jira = Jira(cfg.jira_base_url, cfg.jira_email, cfg.jira_api_token, cfg.jira_project_key, audit, dry)
    diagnoser = Diagnoser(cfg, kube, grafana, github, audit)
    return Agent(cfg, jira, github, kube, grafana, diagnoser, StateStore(cfg.state_db), audit)


def cmd_run(cfg: Config) -> None:
    agent = build(cfg)
    stop = {"flag": False}

    def _stop(signum, _frame):
        log.info("received signal %s, stopping after this cycle", signum)
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("AI SRE agent started: project=%s repo=%s model=%s dry_run=%s",
             cfg.jira_project_key, cfg.github_repo, cfg.model, cfg.dry_run)
    agent.audit.write("agent_started", model=cfg.model, repo=cfg.github_repo, dry_run=cfg.dry_run)
    log.info("watching Jira project %s for open tickets labelled '%s' every %ss (Ctrl-C to stop)",
             cfg.jira_project_key, cfg.jira_triage_label, cfg.poll_seconds)
    agent.recover()
    heartbeat_every = max(1, 300 // max(cfg.poll_seconds, 1))  # ~5 minutes
    ticks = 0
    while not stop["flag"]:
        agent.tick()
        ticks += 1
        if ticks % heartbeat_every == 0:
            log.info("still watching (%d incident(s) in local state)", len(agent.state.all()))
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


def cmd_status(cfg: Config) -> None:
    store = StateStore(cfg.state_db)
    rows = store.all()
    if not rows:
        print("No incidents handled yet.")
    for r in rows:
        print(f"{r['key']:10} {r['stage']:10} attempt={r.get('attempt', 1)} "
              f"{r.get('namespace')}/{r.get('workload')} pr={r.get('pr_url', '-')}")
        for label, t, d in fmt.timeline_rows(r):
            print(f"    {label:22} {t}  (+{d})")


def cmd_selftest(cfg: Config) -> int:
    agent = build(cfg, dry_run=True)
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
    check("Kubernetes API (list pods in shop)", lambda: _expect_ok(agent.kube.run(["get", "pods", "-n", "shop"])))
    check("Grafana / Prometheus query", lambda: str(agent.grafana.promql("up").get("status")))
    check("Grafana alert state", lambda: f"{len(agent.grafana.active_alerts())} active")
    check("Jira triage queue", lambda: f"{len(agent.jira.triage_queue(cfg.jira_triage_label))} open")
    check("GitHub repo read", lambda: ", ".join(agent.github.list_dir(cfg.allowed_paths[0].rstrip("/"))[:5]))

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
        code, out = agent.kube.run(args)
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
    sub.add_parser("run")
    sub.add_parser("once")
    d = sub.add_parser("diagnose")
    d.add_argument("key")
    sub.add_parser("status")
    sub.add_parser("selftest")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.cmd == "status":
        import os
        cmd_status(Config(**{**_status_defaults(), "state_db": os.environ.get("STATE_DB", _status_defaults()["state_db"])}))
        return
    cfg = Config.from_env()
    try:
        if args.cmd == "run":
            cmd_run(cfg)
        elif args.cmd == "once":
            agent = build(cfg)
            agent.tick()
        elif args.cmd == "diagnose":
            cmd_diagnose(cfg, args.key)
        elif args.cmd == "selftest":
            sys.exit(cmd_selftest(cfg))
    except RuntimeError as exc:  # API errors: show the message, not a traceback (-v for details)
        if args.verbose:
            raise
        sys.exit(f"error: {exc}")


def _status_defaults() -> dict:
    """status only needs the DB path; avoid requiring every secret."""
    empty = dict.fromkeys([
        "anthropic_api_key", "model", "kubeconfig", "kubectl_bin", "argocd_namespace", "grafana_url",
        "grafana_token", "grafana_prom_uid", "jira_base_url", "jira_email", "jira_api_token",
        "jira_project_key", "jira_triage_label", "jira_transition_start", "jira_transition_review",
        "jira_transition_done", "github_token", "github_repo", "github_base_branch", "github_api_url"], "")
    return {**empty, "max_turns": 0, "state_db": ".agent/state.db"}


if __name__ == "__main__":
    main()
