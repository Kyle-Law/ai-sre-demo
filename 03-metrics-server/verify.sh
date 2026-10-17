#!/usr/bin/env bash
source "$(dirname "$0")/../lib/common.sh"
need_context

echo "metrics-server"
check "deployment ready" kubectl -n kube-system rollout status deploy/metrics-server --timeout=5s
check "metrics.k8s.io API available" bash -c "kubectl get apiservice v1beta1.metrics.k8s.io -o jsonpath='{.status.conditions[?(@.type==\"Available\")].status}' | grep -q True"
check "kubectl top nodes" kubectl top nodes
check "kubectl top pods -A" kubectl top pods -A
summary
