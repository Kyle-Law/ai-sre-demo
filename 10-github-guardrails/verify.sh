#!/usr/bin/env bash
# Checks the repo guardrails through the GitHub API (gh must act as the repo owner).
source "$(dirname "$0")/../lib/common.sh"
need_bin gh
need GITHUB_REPO GITHUB_AGENT_LOGIN

protection() { gh api "repos/${GITHUB_REPO}/branches/main/protection" 2>/dev/null; }
protected_with_review() { protection | python3 -c '
import sys, json
p = json.load(sys.stdin)
r = p["required_pull_request_reviews"]
sys.exit(0 if r["required_approving_review_count"] >= 1 and r["require_code_owner_reviews"] else 1)'; }
required_checks() { protection | python3 -c '
import sys, json
c = set(json.load(sys.stdin)["required_status_checks"]["contexts"])
sys.exit(0 if {"validate-manifests", "agent-scope-guard"} <= c else 1)'; }
agent_variable_set() { [[ "$(gh variable get AGENT_GITHUB_LOGIN --repo "$GITHUB_REPO")" == "$GITHUB_AGENT_LOGIN" ]]; }
agent_not_codeowner() { ! grep -q "@${GITHUB_AGENT_LOGIN%\[bot\]}" .github/CODEOWNERS; }
app_key_present() { [[ -f github-app.pem ]] && [[ "$(stat -f %Lp github-app.pem 2>/dev/null || stat -c %a github-app.pem)" == 600 ]]; }

echo "GitHub guardrails on ${GITHUB_REPO}"
check "main requires 1 approving CODEOWNER review" protected_with_review
check "required checks: validate-manifests + agent-scope-guard" required_checks
check "repo variable AGENT_GITHUB_LOGIN=${GITHUB_AGENT_LOGIN}" agent_variable_set
check "agent is not a code owner" agent_not_codeowner
check "label 'ai-generated' exists" gh label list --repo "$GITHUB_REPO" --search ai-generated --json name -q '.[0].name'
if [[ "$GITHUB_AGENT_LOGIN" == *"[bot]" ]]; then
  check "GitHub App private key github-app.pem present (0600)" app_key_present
fi
summary
