#!/usr/bin/env bash
# One-time: replace placeholders with your repo URL and Grafana URL, then commit.
#   ./scripts/configure-repo.sh            (reads demo.env; safe to re-run)
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source ./demo.env

: "${GITHUB_REPO:?set GITHUB_REPO in demo.env}"
REPO_URL="https://github.com/${GITHUB_REPO}.git"
GRAFANA_URL="${GRAFANA_URL:-http://localhost:30300}"
GRAFANA_URL="${GRAFANA_URL%/}/"
OWNER="${GITHUB_HUMAN_REVIEWER:-${GITHUB_REPO%%/*}}"

echo "Repo URL     : ${REPO_URL}"
echo "Grafana URL  : ${GRAFANA_URL}"
echo "Code owner   : @${OWNER}"

# grep exits 1 once nothing is left to replace (re-runs); that's fine.
{ grep -rl --include='*.yaml' 'https://github.com/YOUR_GITHUB_ORG/ai-sre-demo.git' bootstrap argocd || true; } \
  | xargs -r sed -i.bak "s#https://github.com/YOUR_GITHUB_ORG/ai-sre-demo.git#${REPO_URL}#g"
sed -i.bak "s#root_url: GRAFANA_PUBLIC_URL#root_url: ${GRAFANA_URL}#" platform/monitoring/values.yaml
sed -i.bak "s#@YOUR_GITHUB_USER#@${OWNER}#g" .github/CODEOWNERS
find . -name '*.bak' -not -path './.git/*' -delete

echo
echo "Done. Review with 'git diff', then:"
echo "  git add -A && git commit -m 'chore: configure demo repo' && git push"
