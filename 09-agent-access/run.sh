#!/usr/bin/env bash
# Step 09: the agent's read-only identity: a ServiceAccount + RBAC via ArgoCD.
source "$(dirname "$0")/../lib/common.sh"
need_context
need_namespace shop 06
need_pushed 09-agent-access

step "ArgoCD Application 'agent-access'"
kubectl apply -f 09-agent-access/application.yaml
wait_app agent-access 300

cat <<EOF

Next:
  make verify-09                              # prove the ServiceAccount is read-only
  ./09-agent-access/create-grafana-token.sh   # Viewer token for the agent -> agent.env (step 11)
EOF
