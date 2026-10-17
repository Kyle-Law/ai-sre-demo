#!/usr/bin/env bash
# Step 07: Grafana alert rules via ArgoCD.
source "$(dirname "$0")/../lib/common.sh"
need_context
need_namespace monitoring 05
need_pushed 07-alert-rules

step "ArgoCD Application 'alert-rules'"
kubectl apply -f 07-alert-rules/application.yaml
wait_app alert-rules 300

step "Waiting for Grafana's sidecar to load the rules"
for _ in $(seq 1 30); do
  n=$(grafana_api /api/v1/provisioning/alert-rules 2>/dev/null | python3 -c 'import sys,json; print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)
  [[ "$n" -ge 5 ]] && break
  sleep 5
done
info "${n:-0} rules loaded in folder 'AI SRE Demo'"
echo "Next: make verify-07, then make step-08"
