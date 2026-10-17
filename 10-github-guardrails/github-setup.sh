#!/usr/bin/env bash
# Configure the GitHub repo guardrails with the gh CLI (run as a repo admin):
#   * branch protection on main: PR required, 1 approval, CODEOWNERS review,
#     required CI checks, stale approvals dismissed
#   * repo variable AGENT_GITHUB_LOGIN used by the agent-scope CI guard
#   * labels used on agent PRs
#   ./10-github-guardrails/github-setup.sh   (gh must act as the repo owner: GH_TOKEN=... if needed)
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source ./demo.env
: "${GITHUB_REPO:?}" "${GITHUB_AGENT_LOGIN:?}"

echo "Protecting main on ${GITHUB_REPO}"
gh api -X PUT "repos/${GITHUB_REPO}/branches/main/protection" --input - <<'EOF'
{
  "required_status_checks": { "strict": true, "contexts": ["validate-manifests", "agent-scope-guard"] },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "require_code_owner_reviews": true,
    "dismiss_stale_reviews": true
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF
# enforce_admins=false lets the demo operator push scenario commits straight to
# main (simulating "a bad change that already shipped"). The agent account is
# NOT an admin, so it must always go through a reviewed PR.

echo "Setting repo variable AGENT_GITHUB_LOGIN=${GITHUB_AGENT_LOGIN}"
gh variable set AGENT_GITHUB_LOGIN --repo "${GITHUB_REPO}" --body "${GITHUB_AGENT_LOGIN}"

for label in "ai-generated:7057ff:Opened by the AI SRE agent" "incident:d73a4a:Incident remediation"; do
  IFS=: read -r name color desc <<<"$label"
  gh label create "$name" --repo "${GITHUB_REPO}" --color "$color" --description "$desc" --force >/dev/null
done
if [[ "${GITHUB_AGENT_LOGIN}" == *"[bot]" ]]; then
  slug="${GITHUB_AGENT_LOGIN%\[bot\]}"
  echo "Done. Make sure the GitHub App is installed on ${GITHUB_REPO} only:"
  echo "  https://github.com/apps/${slug}/installations/new"
else
  echo "Done. Make sure ${GITHUB_AGENT_LOGIN} has Write (not Admin/Maintain) access to the repo."
fi
