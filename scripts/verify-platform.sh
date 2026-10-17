#!/usr/bin/env bash
# Pre-demo health check (admin kubeconfig). Run before every rehearsal / show.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
ok=0; bad=0
check() {
  if eval "$2" >/dev/null 2>&1; then ok=$((ok+1)); printf '  \033[32mOK\033[0m   %s\n' "$1"
  else bad=$((bad+1)); printf '  \033[31mFAIL\033[0m %s\n' "$1"; fi
}

echo "ArgoCD applications"
for app in root monitoring monitoring-config ai-sre shop; do
  check "$app Synced/Healthy" \
    "[[ \$(kubectl -n argocd get application $app -o jsonpath='{.status.sync.status}/{.status.health.status}') == Synced/Healthy ]]"
done
echo "Workloads"
check "checkout 2/2 available" "[[ \$(kubectl -n shop get deploy checkout -o jsonpath='{.status.availableReplicas}') == 2 ]]"
check "alert-bridge ready" "kubectl -n ai-sre rollout status deploy/alert-bridge --timeout=5s"
check "grafana ready" "kubectl -n monitoring get pods -l app.kubernetes.io/name=grafana -o jsonpath='{.items[0].status.containerStatuses[*].ready}' | grep -vq false"
check "no node cordoned" "! kubectl get nodes -o jsonpath='{.items[*].spec.unschedulable}' | grep -q true"
echo "Alerting"
check "alert rules ConfigMap present" "kubectl -n monitoring get configmap ai-sre-alert-rules"
check "Jira secret present" "kubectl -n ai-sre get secret jira-credentials"
echo "Git"
check "demo-baseline tag exists" "git rev-parse -q --verify refs/tags/demo-baseline"
check "apps/shop matches baseline" "git diff --quiet demo-baseline -- apps/shop"

echo
[[ $bad -eq 0 ]] && echo "Ready for the demo ($ok checks)." || { echo "$bad problem(s) found."; exit 1; }
