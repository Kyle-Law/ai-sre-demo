#!/usr/bin/env bash
# Run the AI SRE agent on this machine against the kind cluster.
#   ./11-agent/run.sh [run|once|selftest|status|diagnose INC-1]   (default: run)
#   DRY_RUN=true ./11-agent/run.sh      # investigate, print Jira comments / PRs, write nothing
#
# Reads agent.env (from 11-agent/.env.example), keeps state + audit log in .agent/,
# and installs the agent into .venv on first use.
set -euo pipefail
cd "$(dirname "$0")/.."

VENV=.venv
if [[ ! -x "$VENV/bin/ai-sre-agent" || 11-agent/pyproject.toml -nt "$VENV/bin/ai-sre-agent" ]]; then
  echo "Installing agent into $VENV ..." >&2
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -e 11-agent
  touch "$VENV/bin/ai-sre-agent"
fi

[[ -f agent.env ]] || { echo "agent.env missing: cp 11-agent/.env.example agent.env and fill it in" >&2; exit 1; }
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
[[ -f "$KUBECONFIG" ]] || { echo "$KUBECONFIG missing: make step-09" >&2; exit 1; }

exec "$VENV/bin/ai-sre-agent" "${@:-run}"
