#!/usr/bin/env bash
source "$(dirname "$0")/../lib/common.sh"
need_context

echo "ArgoCD"
for d in argocd-server argocd-repo-server argocd-applicationset-controller argocd-redis; do
  check "$d ready" kubectl -n argocd rollout status "deploy/$d" --timeout=5s
done
check "application-controller ready" kubectl -n argocd rollout status statefulset/argocd-application-controller --timeout=5s
check "git polling every 30s" bash -c "[[ \$(kubectl -n argocd get cm argocd-cm -o jsonpath='{.data.timeout\.reconciliation}') == 30s ]]"
check "UI answers on https://localhost:30443" curl -fsSk https://localhost:30443/healthz
check "repo reachable: https://github.com/${GITHUB_REPO}" git ls-remote --exit-code "https://github.com/${GITHUB_REPO}.git" HEAD
summary
