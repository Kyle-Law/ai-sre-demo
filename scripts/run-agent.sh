#!/usr/bin/env bash
# Run the AI SRE agent on this machine against the kind cluster.
#   ./scripts/run-agent.sh [run|once|selftest|status|diagnose INC-1]   (default: run)
#   DRY_RUN=true ./scripts/run-agent.sh      # investigate, print Jira comments / PRs, write nothing
#
# Reads agent.env (from agent/.env.example), keeps state + audit log in .agent/,
# and installs the agent into .venv on first use.
set -euo pipefail
cd "$(dirname "$0")/.."

VENV=.venv
if [[ ! -x "$VENV/bin/ai-sre-agent" || agent/pyproject.toml -nt "$VENV/bin/ai-sre-agent" ]]; then
  echo "Installing agent into $VENV ..." >&2
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -e agent
  touch "$VENV/bin/ai-sre-agent"
fi

[[ -f agent.env ]] || { echo "agent.env missing: cp agent/.env.example agent.env and fill it in" >&2; exit 1; }
dry_override="${DRY_RUN:-}"
# Never inherit your admin KUBECONFIG: the agent only gets the read-only one.
unset KUBECONFIG
set -a
# shellcheck disable=SC1091
source ./agent.env
set +a
[[ -n "$dry_override" ]] && export DRY_RUN="$dry_override"
export KUBECONFIG="${KUBECONFIG:-agent.kubeconfig}"
export KUBECACHEDIR="${KUBECACHEDIR:-.agent/kube-cache}"
[[ -f "$KUBECONFIG" ]] || { echo "$KUBECONFIG missing: make agent-kubeconfig" >&2; exit 1; }

exec "$VENV/bin/ai-sre-agent" "${@:-run}"
