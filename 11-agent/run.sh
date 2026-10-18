#!/usr/bin/env bash
# Step 11: check the agent's code and agent.env on this machine before step 12 puts it in the
# cluster. The agent itself never runs here: its kubectl only works inside its pod.
#   ./11-agent/run.sh            # install into .venv, offline tests, load agent.env
#   ./11-agent/run.sh selftest   # (make verify-11) Grafana, Jira and GitHub with agent.env's credentials
set -euo pipefail
cd "$(dirname "$0")/.."

VENV=.venv
if [[ ! -x "$VENV/bin/ai-sre-agent" || 11-agent/pyproject.toml -nt "$VENV/bin/ai-sre-agent" ]]; then
  echo "Installing agent into $VENV ..." >&2
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -e '11-agent[test]'
  touch "$VENV/bin/ai-sre-agent"
fi
[[ -f agent.env ]] || { echo "agent.env missing: cp 11-agent/.env.example agent.env and fill it in" >&2; exit 1; }

if [[ "${1:-}" == "" ]]; then
  echo "Offline tests (the agent's lifecycle against fakes)"
  "$VENV/bin/python" -m pytest -q 11-agent/tests
fi
set -a
# shellcheck disable=SC1091
source ./agent.env
set +a
case "${1:-}" in
  selftest) exec "$VENV/bin/ai-sre-agent" selftest ;;
  "") ;;
  *) echo "usage: $0 [selftest]   (everything else runs in the cluster, see step 12)" >&2; exit 2 ;;
esac

echo "agent.env"
"$VENV/bin/python" -c 'from ai_sre_agent.config import Config; c = Config.from_env()
print(f"  loads: model {c.model}, Jira project {c.jira_project_key}, repo {c.github_repo}")'
cat <<MSG

Next: make verify-11 (Grafana, Jira and GitHub with these credentials), then make step-12
MSG
