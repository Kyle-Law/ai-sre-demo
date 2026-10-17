#!/usr/bin/env bash
source "$(dirname "$0")/../lib/common.sh"
need_context

echo "Cilium"
check "cilium DaemonSet ready" kubectl -n kube-system rollout status ds/cilium --timeout=5s
check "cilium-operator ready" kubectl -n kube-system rollout status deploy/cilium-operator --timeout=5s
check "cilium agent reports OK" bash -c "kubectl -n kube-system exec ds/cilium -c cilium-agent -- cilium-dbg status --brief | grep -q OK"
check "hubble-relay ready" kubectl -n kube-system rollout status deploy/hubble-relay --timeout=5s
echo "Cluster networking"
check "node Ready" kubectl wait --for=condition=Ready node --all --timeout=5s
check "coredns ready" kubectl -n kube-system rollout status deploy/coredns --timeout=5s
check "pod can resolve and reach the API service" \
  kubectl run "cni-check-$RANDOM" --rm -i --restart=Never --quiet --image=busybox:1.36 --timeout=90s -- \
  sh -c 'nslookup kubernetes.default.svc.cluster.local && nc -z -w 3 kubernetes.default.svc.cluster.local 443'
summary
