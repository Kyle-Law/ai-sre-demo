#!/usr/bin/env bash
# One-time: replace placeholders with your repo URL, Grafana URL and code owner.
#   ./00-prereqs/configure-repo.sh            (reads demo.env; safe to re-run)
source "$(dirname "$0")/../lib/common.sh"
need GITHUB_REPO

REPO_URL="https://github.com/${GITHUB_REPO}.git"
GRAFANA_URL="${GRAFANA_URL:-http://localhost:30300}"
GRAFANA_URL="${GRAFANA_URL%/}/"
OWNER="${GITHUB_HUMAN_REVIEWER:-${GITHUB_REPO%%/*}}"

echo "Repo URL     : ${REPO_URL}"
echo "Grafana URL  : ${GRAFANA_URL}"
echo "Code owner   : @${OWNER}"

# ArgoCD Applications / AppProject in every step folder. grep exits 1 once
# nothing is left to replace (re-runs); that's fine.
{ grep -rl --include='*.yaml' 'https://github.com/YOUR_GITHUB_ORG/ai-sre-demo.git' [0-9][0-9]-*/ || true; } \
  | xargs -r sed -i.bak "s#https://github.com/YOUR_GITHUB_ORG/ai-sre-demo.git#${REPO_URL}#g"
sed -i.bak "s#root_url: GRAFANA_PUBLIC_URL#root_url: ${GRAFANA_URL}#" 05-monitoring/values.yaml
sed -i.bak "s#@YOUR_GITHUB_USER#@${OWNER}#g" .github/CODEOWNERS
find . -name '*.bak' -not -path './.git/*' -delete

echo
echo "Done. Review with 'git diff', then:"
echo "  git add -A && git commit -m 'chore: configure demo repo' && git push"
