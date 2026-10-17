#!/usr/bin/env bash
# Step 02: install Cilium as the cluster's CNI.
source "$(dirname "$0")/../lib/common.sh"
need_bin helm
need_context
CILIUM_VERSION="${CILIUM_VERSION:-1.20.3}"

step "Cilium ${CILIUM_VERSION}"
helm upgrade --install cilium cilium --repo https://helm.cilium.io \
  --version "$CILIUM_VERSION" --namespace kube-system \
  -f 02-cni-cilium/values.yaml --wait --timeout 10m

step "Waiting for the node to become Ready"
kubectl wait --for=condition=Ready node --all --timeout=300s
kubectl -n kube-system rollout status deploy/coredns --timeout=180s
kubectl get nodes

cat <<EOF

Pod network is up. Hubble UI (flow visibility):
  kubectl -n kube-system port-forward svc/hubble-ui 12000:80   ->  http://localhost:12000
Next: make verify-02, then make step-03
EOF
