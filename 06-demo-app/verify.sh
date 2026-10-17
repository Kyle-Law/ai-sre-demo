#!/usr/bin/env bash
source "$(dirname "$0")/../lib/common.sh"
need_context

two_replicas() { [[ "$(kubectl -n shop get deploy checkout -o jsonpath='{.status.availableReplicas}')" == 2 ]]; }
# The AppProject must refuse a Secret even though the Application could render one.
project_blocks_secrets() {
  kubectl -n argocd get appproject shop -o jsonpath='{.spec.namespaceResourceBlacklist[*].kind}' | grep -qw Secret
}

echo "Demo app"
check "ArgoCD app 'shop' Synced/Healthy" app_healthy shop
check "checkout 2/2 available" two_replicas
check "service answers /healthz" kubectl -n shop run "probe-$RANDOM" --rm -i --restart=Never --quiet \
  --image=busybox:1.36 --timeout=60s -- wget -qO- -T 5 http://checkout/healthz
check "AppProject 'shop' blacklists Secrets" project_blocks_secrets
check "AppProject 'shop' only targets namespace shop" \
  bash -c "[[ \$(kubectl -n argocd get appproject shop -o jsonpath='{.spec.destinations[*].namespace}') == shop ]]"
summary
