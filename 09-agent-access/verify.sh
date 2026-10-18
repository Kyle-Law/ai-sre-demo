#!/usr/bin/env bash
# Runs the line-by-line RBAC proof for the agent's ServiceAccount (impersonated from your context).
source "$(dirname "$0")/../lib/common.sh"
need_context

echo "ArgoCD"
check "ArgoCD app 'agent-access' Synced/Healthy" app_healthy agent-access
summary
echo
./09-agent-access/verify-rbac.sh
