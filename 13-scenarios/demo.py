#!/usr/bin/env python3
"""Demo scenario driver: break the checkout service on purpose, then reset it.

Most scenarios break the app *through git*, exactly like a real bad change:
the script edits 06-demo-app/manifests/, commits with a realistic message and pushes to
main. ArgoCD then rolls the change out, Grafana alerts, a Jira ticket opens,
and the AI agent has to find the offending commit and propose a fix PR.

One scenario (06) breaks the cluster *outside* git to show the agent
escalating instead of opening a PR.

Usage (run from the repo root, with push rights to main):
    python3 13-scenarios/demo.py list
    python3 13-scenarios/demo.py baseline          # tag the known-good state (once)
    python3 13-scenarios/demo.py inject 01-oomkilled
    python3 13-scenarios/demo.py status
    python3 13-scenarios/demo.py reset             # restore the demo app from the baseline tag

Options:
    --no-push      commit locally only (rehearsal / review the diff first)
    --dry-run      print what would change, touch nothing

Stdlib only. Scenario 06 additionally needs an *admin* kubectl context (the
kind-ai-sre context that `make cluster-up` selects).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASELINE_TAG = "demo-baseline"
APP_DIR = "06-demo-app/manifests"
STATE_FILE = REPO / ".demo-state.json"

DEPLOY = f"{APP_DIR}/deployment.yaml"
CONFIGMAP = f"{APP_DIR}/configmap.yaml"

SCENARIOS: dict[str, dict] = {
    "01-oomkilled": {
        "title": "Memory limit 'rightsized' below the working set -> OOMKilled",
        "alert": "ContainerOOMKilled",
        "time_to_alert": "~2 min",
        "commit_message": "chore(checkout): rightsize memory request/limit per FinOps report\n\n"
        "FinOps dashboard shows avg usage well under the limit; trimming to save cost.",
        # Request and limit both move: the API server rejects request > limit, so
        # lowering only the limit would never roll out (ArgoCD sync error, no OOM).
        "edits": [
            {"file": DEPLOY, "find": "              memory: 128Mi\n            limits:\n              memory: 256Mi",
             "replace": "              memory: 48Mi\n            limits:\n              memory: 64Mi"},
        ],
        "expected_fix": "Restore memory to >= the working set (request 128Mi, limit 256Mi), e.g. revert the commit.",
    },
    "02-bad-image-tag": {
        "title": "Typo'd hotfix image tag -> ImagePullBackOff",
        "alert": "ContainerImagePullFailing",
        "time_to_alert": "~2 min",
        "commit_message": "fix(checkout): roll out 6.15.0-hotfix1 for cart rounding bug",
        "edits": [
            {"file": DEPLOY, "find": "image: ghcr.io/stefanprodan/podinfo:6.15.0\n",
             "replace": "image: ghcr.io/stefanprodan/podinfo:6.15.0-hotfix1\n"},
        ],
        "expected_fix": "Point the image back to an existing tag (6.15.0).",
    },
    "03-readiness-probe": {
        "title": "Readiness probe moved to the wrong port -> rollout stuck",
        "alert": "DeploymentRolloutStuck",
        "time_to_alert": "~3-4 min (120s progress deadline + 1m pending)",
        "commit_message": "refactor(checkout): standardise health probes on port 8080",
        "edits": [
            {"file": DEPLOY,
             "find": "          readinessProbe:\n            httpGet:\n              path: /readyz\n              port: 9898",
             "replace": "          readinessProbe:\n            httpGet:\n              path: /readyz\n              port: 8080"},
        ],
        "expected_fix": "Readiness probe port back to 9898 (the port the container listens on).",
    },
    "04-configmap-key": {
        "title": "ConfigMap key renamed but Deployment still references it -> CreateContainerConfigError",
        "alert": "ContainerConfigError",
        "time_to_alert": "~2 min",
        "commit_message": "refactor(checkout): rename ui.message config key to ui.banner",
        "edits": [
            {"file": CONFIGMAP, "find": "  ui.message: ", "replace": "  ui.banner: "},
            {"file": DEPLOY, "find": 'demo.ai-sre/config-revision: "1"',
             "replace": 'demo.ai-sre/config-revision: "2"'},
        ],
        "expected_fix": "Rename the key back to ui.message (or update the Deployment's configMapKeyRef to ui.banner).",
    },
    "05-cpu-request-typo": {
        "title": "CPU request typo (50 cores instead of 500m) -> Pending / Unschedulable",
        "alert": "PodUnschedulable",
        "time_to_alert": "~2 min",
        "commit_message": "perf(checkout): raise CPU request ahead of peak traffic",
        "edits": [
            {"file": DEPLOY, "find": "              cpu: 50m\n", "replace": '              cpu: "50"\n'},
        ],
        "expected_fix": "Set requests.cpu to a schedulable value (500m was clearly intended, or back to 50m).",
    },
    "06-node-cordoned": {
        "title": "Node cordoned out-of-band -> Pending pods (NOT fixable in git: agent must escalate)",
        "alert": "PodUnschedulable",
        "time_to_alert": "~2 min",
        "cluster_actions": [
            # "Maintenance" cordon that someone forgot to undo...
            "kubectl cordon -l kubernetes.io/os=linux",
            # ...then a routine pod replacement can no longer be scheduled.
            "kubectl -n shop delete $(kubectl -n shop get pod -l app=checkout -o name | head -n1) --wait=false",
        ],
        "reset_actions": [
            "kubectl uncordon -l kubernetes.io/os=linux",
        ],
        "expected_fix": "No PR. Agent comments the diagnosis (node unschedulable) and escalates to a human to uncordon.",
    },
}


def run(cmd: list[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=REPO, check=check, text=True, capture_output=capture)


def git(*args: str) -> str:
    return run(["git", *args], capture=True).stdout.strip()


def sh(command: str) -> None:
    """Cluster actions are shell one-liners (they need $(...) substitution)."""
    print("  $", command)
    subprocess.run(command, cwd=REPO, shell=True, check=False)


def ensure_clean_main() -> None:
    if git("status", "--porcelain", "--", APP_DIR):
        sys.exit(f"Uncommitted changes in {APP_DIR}; commit or stash them first.")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main":
        sys.exit(f"Run scenarios from the main branch (currently on {branch}).")


def pull() -> None:
    run(["git", "pull", "--ff-only", "--quiet"], check=False, capture=True)


def apply_edits(edits: list[dict], dry_run: bool) -> list[str]:
    changed = []
    for edit in edits:
        path = REPO / edit["file"]
        text = path.read_text()
        count = text.count(edit["find"])
        if count != 1:
            sys.exit(
                f"Cannot apply scenario: expected exactly 1 match in {edit['file']} but found {count}.\n"
                f"Is another scenario still active? Run: python3 13-scenarios/demo.py reset"
            )
        if dry_run:
            print(f"--- {edit['file']}\n- {edit['find']!r}\n+ {edit['replace']!r}")
        else:
            path.write_text(text.replace(edit["find"], edit["replace"]))
        changed.append(edit["file"])
    return changed


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def load_state() -> dict:
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}


def cmd_list(_args) -> None:
    for sid, s in SCENARIOS.items():
        kind = "cluster (no git)" if "cluster_actions" in s else "git commit"
        print(f"{sid:22} {s['alert']:28} {s['time_to_alert']:12} [{kind}]\n    {s['title']}")


def cmd_baseline(args) -> None:
    ensure_clean_main()
    pull()
    git("tag", "-f", BASELINE_TAG)
    if not args.no_push:
        run(["git", "push", "-f", "origin", BASELINE_TAG], capture=True)
    print(f"Tagged {git('rev-parse', '--short', 'HEAD')} as {BASELINE_TAG}")


def cmd_inject(args) -> None:
    sid = args.scenario
    if sid not in SCENARIOS:
        sys.exit(f"Unknown scenario {sid}. Try: python3 13-scenarios/demo.py list")
    s = SCENARIOS[sid]
    print(f"Injecting {sid}: {s['title']}")

    if "cluster_actions" in s:
        for cmd in s["cluster_actions"]:
            if args.dry_run:
                print("  (dry-run) $", cmd)
            else:
                sh(cmd)
        if not args.dry_run:
            save_state({"active": sid})
        print(f"\nExpected alert: {s['alert']} in {s['time_to_alert']}. Expected agent outcome: {s['expected_fix']}")
        return

    ensure_clean_main()
    pull()
    changed = apply_edits(s["edits"], args.dry_run)
    if args.dry_run:
        return
    git("add", *changed)
    git("commit", "--quiet", "-m", s["commit_message"])
    sha = git("rev-parse", "--short", "HEAD")
    if not args.no_push:
        run(["git", "push", "--quiet", "origin", "main"])
    save_state({"active": sid, "commit": sha})
    print(textwrap.dedent(f"""
        Committed {sha}: {s['commit_message'].splitlines()[0]}
        {'Pushed to origin/main.' if not args.no_push else 'NOT pushed (--no-push).'}

        Expected alert : {s['alert']} ({s['time_to_alert']})
        Expected fix   : {s['expected_fix']}
    """))


def cmd_reset(args) -> None:
    state = load_state()
    active = state.get("active")
    # Undo out-of-band cluster changes (scenario 06) first.
    if args.uncordon or "reset_actions" in SCENARIOS.get(active or "", {}):
        for cmd in SCENARIOS["06-node-cordoned"]["reset_actions"]:
            if args.dry_run:
                print("  (dry-run) $", cmd)
            else:
                sh(cmd)

    ensure_clean_main()
    pull()
    if run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{BASELINE_TAG}"], check=False, capture=True).returncode:
        run(["git", "fetch", "--quiet", "origin", "tag", BASELINE_TAG], check=False)
    diff = run(["git", "diff", "HEAD", BASELINE_TAG, "--", APP_DIR], check=False, capture=True)
    if diff.returncode:
        sys.exit(f"Tag {BASELINE_TAG} not found. Run: python3 13-scenarios/demo.py baseline")
    if not diff.stdout:
        print(f"{APP_DIR} already matches {BASELINE_TAG}.")
    elif args.dry_run:
        print(diff.stdout)
        return
    else:
        git("checkout", BASELINE_TAG, "--", APP_DIR)
        git("commit", "--quiet", "-m", f"chore(demo): reset {APP_DIR} to {BASELINE_TAG}")
        if not args.no_push:
            run(["git", "push", "--quiet", "origin", "main"])
        print(f"Reset {APP_DIR} to {BASELINE_TAG} ({git('rev-parse', '--short', 'HEAD')}).")
    if not args.dry_run:
        save_state({})


def cmd_status(_args) -> None:
    state = load_state()
    print(f"Active scenario: {state.get('active') or 'none'}")
    diff = run(["git", "diff", "--stat", BASELINE_TAG, "--", APP_DIR], check=False, capture=True)
    if diff.returncode:
        print(f"(no {BASELINE_TAG} tag yet — run: python3 13-scenarios/demo.py baseline)")
    else:
        print(f"Drift from {BASELINE_TAG}:\n{diff.stdout or '  none'}")
    pods = run(["kubectl", "-n", "shop", "get", "pods", "-o", "wide"], check=False, capture=True)
    if pods.returncode == 0:
        print(pods.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-push", action="store_true", help="commit locally, do not push")
    parser.add_argument("--dry-run", action="store_true", help="show changes only")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(func=cmd_list)
    sub.add_parser("baseline").set_defaults(func=cmd_baseline)
    p = sub.add_parser("inject")
    p.add_argument("scenario")
    p.set_defaults(func=cmd_inject)
    r = sub.add_parser("reset")
    r.add_argument("--uncordon", action="store_true", help="also uncordon all nodes (scenario 06)")
    r.set_defaults(func=cmd_reset)
    sub.add_parser("status").set_defaults(func=cmd_status)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
