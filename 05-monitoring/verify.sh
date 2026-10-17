#!/usr/bin/env bash
source "$(dirname "$0")/../lib/common.sh"
need_context

promql_works() { grafana_api '/api/datasources/proxy/uid/prometheus/api/v1/query?query=count(kube_pod_info)' | grep -q '"status":"success"'; }

echo "Monitoring"
check "ArgoCD app 'monitoring' Synced/Healthy" app_healthy monitoring
check "Prometheus ready" kubectl -n monitoring rollout status statefulset/prometheus-kps-kube-prometheus-stack-prometheus --timeout=5s
check "kube-state-metrics ready" kubectl -n monitoring rollout status deploy/kps-kube-state-metrics --timeout=5s
check "Grafana answers on ${GRAFANA_URL:-http://localhost:30300}" grafana_api /api/health
check "Grafana admin login works" grafana_api /api/user
check "Prometheus datasource (uid=prometheus) answers PromQL" promql_works
summary
