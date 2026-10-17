#!/usr/bin/env bash
# Runs the line-by-line RBAC proof with the agent's kubeconfig (not yours).
source "$(dirname "$0")/../lib/common.sh"
need_context
[[ -f agent.kubeconfig ]] || die "agent.kubeconfig missing - run make step-09"

echo "ArgoCD"
check "ArgoCD app 'agent-access' Synced/Healthy" app_healthy agent-access
summary
echo
KUBECONFIG="$ROOT/agent.kubeconfig" ./09-agent-access/verify-rbac.sh
