#!/usr/bin/env bash
# Create a Grafana service account with the Viewer role for the agent and print
# a token for it (-> GRAFANA_TOKEN in the agent's env file). Idempotent.
#   ./scripts/create-grafana-token.sh
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source ./demo.env
GRAFANA="${GRAFANA_URL:-http://localhost:30300}"
AUTH="${GRAFANA_ADMIN_USER:-admin}:${GRAFANA_ADMIN_PASSWORD}"
NAME=ai-sre-agent

api() { curl -fsS -u "$AUTH" -H 'Content-Type: application/json' "$@"; }

SA_ID=$(api "${GRAFANA}/api/serviceaccounts/search?query=${NAME}" \
  | python3 -c "import sys,json; r=[s['id'] for s in json.load(sys.stdin)['serviceAccounts'] if s['name']=='${NAME}']; print(r[0] if r else '')")
if [[ -z "$SA_ID" ]]; then
  SA_ID=$(api -X POST "${GRAFANA}/api/serviceaccounts" -d "{\"name\":\"${NAME}\",\"role\":\"Viewer\"}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
  echo "Created Grafana service account ${NAME} (id ${SA_ID}, role Viewer)" >&2
fi
TOKEN=$(api -X POST "${GRAFANA}/api/serviceaccounts/${SA_ID}/tokens" \
  -d "{\"name\":\"${NAME}-$(date +%s)\",\"secondsToLive\":604800}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['key'])")
echo "Token valid for 7 days. Put this in agent.env:" >&2
echo "GRAFANA_URL=${GRAFANA}"
echo "GRAFANA_TOKEN=${TOKEN}"
