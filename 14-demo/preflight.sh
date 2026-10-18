#!/usr/bin/env bash
# Pre-show health check across every step. Run before each rehearsal / show.
source "$(dirname "$0")/../lib/common.sh"
need_context

two_replicas() { [[ "$(kubectl -n shop get deploy checkout -o jsonpath='{.status.availableReplicas}')" == 2 ]]; }
no_cordon() { ! kubectl get nodes -o jsonpath='{.items[*].spec.unschedulable}' | grep -q true; }
no_firing() { ! grafana_api /api/prometheus/grafana/api/v1/rules | grep -q '"state":"firing"'; }

echo "Cluster (01-03)"
check "node Ready" kubectl wait --for=condition=Ready node --all --timeout=5s
check "Cilium ready" kubectl -n kube-system rollout status ds/cilium --timeout=5s
check "metrics-server answers" kubectl top nodes
echo "ArgoCD applications (05-12)"
for app in monitoring shop alert-rules jira-integration agent-access agent-operator; do
  check "$app Synced/Healthy" app_healthy "$app"
done
echo "Workloads"
check "checkout 2/2 available" two_replicas
check "alert-bridge ready" kubectl -n ai-sre rollout status deploy/alert-bridge --timeout=5s
check "no node cordoned" no_cordon
check "no alert firing in Grafana" no_firing
echo "Agent"
check "agent-controller ready" kubectl -n ai-sre-agent rollout status deploy/agent-controller --timeout=5s
echo "Git"
check "demo-baseline tag exists" git rev-parse -q --verify refs/tags/demo-baseline
check "demo app matches baseline" git diff --quiet demo-baseline -- 06-demo-app/manifests
summary
