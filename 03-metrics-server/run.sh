#!/usr/bin/env bash
# Step 03: metrics-server (resource metrics API for kubectl top / HPA).
source "$(dirname "$0")/../lib/common.sh"
need_context
METRICS_SERVER_VERSION="${METRICS_SERVER_VERSION:-v0.9.0}"

step "metrics-server ${METRICS_SERVER_VERSION}"
kubectl apply -f "https://github.com/kubernetes-sigs/metrics-server/releases/download/${METRICS_SERVER_VERSION}/components.yaml"
# kind kubelets serve self-signed certificates.
if ! kubectl -n kube-system get deploy metrics-server -o jsonpath='{.spec.template.spec.containers[0].args}' | grep -q kubelet-insecure-tls; then
  kubectl -n kube-system patch deploy metrics-server --type json \
    -p '[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
fi
kubectl -n kube-system rollout status deploy/metrics-server --timeout=180s

step "Waiting for the first scrape"
for _ in $(seq 1 18); do kubectl top nodes 2>/dev/null && break; sleep 5; done
echo "Next: make verify-03, then make step-04"
