#!/usr/bin/env bash
# Step 10: the agent's GitHub identity (GitHub App) and the repo guardrails.
#   First run : creates the GitHub App (browser click), then tells you what to fill in.
#   Second run: branch protection, required checks, CI variable, labels.
# gh must act as the repo owner; with several gh accounts use e.g.
#   GH_TOKEN=$(gh auth token --user <owner>) make step-10
source "$(dirname "$0")/../lib/common.sh"
need_bin gh
need GITHUB_REPO

if [[ -z "${GITHUB_AGENT_LOGIN:-}" || "${GITHUB_AGENT_LOGIN}" == your-app-slug* ]]; then
  step "Creating the agent's GitHub App"
  python3 10-github-guardrails/create-github-app.py
  echo
  echo "Install the App, set GITHUB_AGENT_LOGIN in demo.env, then run make step-10 again."
  exit 0
fi

step "Guardrails on ${GITHUB_REPO} (agent: ${GITHUB_AGENT_LOGIN})"
./10-github-guardrails/github-setup.sh
echo "Next: make verify-10, then make step-11"
