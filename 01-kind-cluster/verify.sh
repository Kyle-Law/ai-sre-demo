#!/usr/bin/env bash
source "$(dirname "$0")/../lib/common.sh"
need_context

echo "kind cluster"
check "cluster '${CLUSTER}' exists" bash -c "kind get clusters | grep -qx '${CLUSTER}'"
check "API server reachable" kubectl get --raw /readyz
check "control-plane node registered" kubectl get node "${CLUSTER}-control-plane"
check "Grafana port 30300 mapped to localhost" bash -c "docker port '${CLUSTER}-control-plane' | grep -q '30300/tcp -> 127.0.0.1:30300'"
check "ArgoCD port 30443 mapped to localhost" bash -c "docker port '${CLUSTER}-control-plane' | grep -q '30443/tcp -> 127.0.0.1:30443'"
summary
