#!/usr/bin/env bash
# Step 05: Prometheus + Grafana via ArgoCD.
source "$(dirname "$0")/../lib/common.sh"
need_context
need GRAFANA_ADMIN_PASSWORD
need_pushed 05-monitoring

step "Grafana admin Secret (from demo.env, never in git)"
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
kubectl -n monitoring create secret generic grafana-admin \
  --from-literal=admin-user="${GRAFANA_ADMIN_USER:-admin}" \
  --from-literal=admin-password="${GRAFANA_ADMIN_PASSWORD}" \
  --dry-run=client -o yaml | kubectl apply -f -

step "ArgoCD Application 'monitoring'"
kubectl apply -f 05-monitoring/application.yaml
wait_app monitoring 900

cat <<EOF

Grafana: ${GRAFANA_URL:-http://localhost:30300}   (${GRAFANA_ADMIN_USER:-admin} / from demo.env)
Next: make verify-05, then make step-06
EOF
