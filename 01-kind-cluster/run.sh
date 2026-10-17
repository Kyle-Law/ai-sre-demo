#!/usr/bin/env bash
# Step 01: create the kind cluster (no CNI yet).
source "$(dirname "$0")/../lib/common.sh"
need_bin docker kind kubectl

docker info >/dev/null 2>&1 || die "Docker is not running - start Docker Desktop first."
MEM_GB=$(( $(docker info --format '{{.MemTotal}}') / 1024 / 1024 / 1024 ))
(( MEM_GB >= 6 )) || echo "WARNING: Docker has ${MEM_GB} GB RAM; the full stack wants ~6 GB (Docker Desktop > Settings > Resources)." >&2

step "kind cluster '${CLUSTER}'"
if kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  info "already exists"
else
  # No --wait: without a CNI the node can't become Ready until step 02.
  kind create cluster --name "$CLUSTER" --config 01-kind-cluster/cluster.yaml
fi
kubectl config use-context "$KCTX" >/dev/null
kubectl get nodes -o wide

cat <<EOF

kubectl now points at ${KCTX}. The node is NotReady until a CNI is installed:
  kubectl describe node ${CLUSTER}-control-plane | grep -i ready
Next: make step-02
EOF
