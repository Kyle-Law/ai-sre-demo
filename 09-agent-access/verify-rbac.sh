#!/usr/bin/env bash
# Prove the agent's ServiceAccount can read but not write. Great live demo moment.
#   ./09-agent-access/verify-rbac.sh [system:serviceaccount:NS:NAME]
# Uses your admin context to impersonate the ServiceAccount (--as), so the API server
# answers for exactly the identity the agent's pods run as.
set -uo pipefail

AS="${1:-system:serviceaccount:ai-sre:ai-sre-agent}"
pass=0; fail=0
green() { printf '\033[32m%s\033[0m' "$*"; }
red() { printf '\033[31m%s\033[0m' "$*"; }

expect() {  # expect <yes|no> <verb> <resource[/subresource]> [namespace]
  local want="$1" verb="$2" res="$3" ns="${4:-}"
  # "kubectl auth can-i VERB pods/exec" would mean "the pod NAMED exec";
  # subresources must be passed with --subresource.
  local args=(auth can-i "$verb" "${res%%/*}" --as="$AS")
  if [[ "$res" == */* ]]; then args+=(--subresource="${res#*/}"); fi
  if [[ -n "$ns" ]]; then args+=(-n "$ns"); fi
  local got
  got=$(kubectl "${args[@]}" 2>/dev/null | head -n1)
  got=${got:-no}
  if [[ "$got" == "$want" ]]; then
    pass=$((pass + 1)); printf '  %s  %-6s %-30s %-12s -> %s\n' "$(green PASS)" "$verb" "$res" "${ns:-<cluster>}" "$got"
  else
    fail=$((fail + 1)); printf '  %s  %-6s %-30s %-12s -> %s (expected %s)\n' "$(red FAIL)" "$verb" "$res" "${ns:-<cluster>}" "$got" "$want"
  fi
}

echo "Identity: $AS"
echo
echo "Should be ALLOWED (diagnosis):"
expect yes get    pods                       shop
expect yes get    pods/log                   shop
expect yes list   events                     shop
expect yes get    deployments.apps           shop
expect yes list   replicasets.apps           shop
expect yes get    configmaps                 shop
expect yes list   nodes
expect yes get    pods.metrics.k8s.io        shop
expect yes get    applications.argoproj.io   argocd
echo
echo "Should be DENIED (no writes, no secrets, no shells):"
expect no  get    secrets                    shop
expect no  list   secrets                    kube-system
expect no  delete pods                       shop
expect no  create pods                       shop
expect no  patch  deployments.apps           shop
expect no  update deployments.apps/scale     shop
expect no  create pods/exec                  shop
expect no  create pods/portforward           shop
expect no  get    configmaps                 kube-system
expect no  update applications.argoproj.io   argocd
expect no  create serviceaccounts/token      ai-sre
expect no  impersonate serviceaccounts       kube-system
expect no  delete nodes
expect no  create clusterrolebindings.rbac.authorization.k8s.io

echo
echo "Live attempt (server-side dry run, nothing is deleted even if allowed):"
kubectl --as="$AS" -n shop delete pod -l app=checkout --dry-run=server 2>&1 | sed 's/^/  /' | head -n3

echo
if [[ $fail -eq 0 ]]; then
  green "All $pass checks passed: the agent's ServiceAccount is read-only."; echo
else
  red "$fail of $((pass + fail)) checks failed."; echo; exit 1
fi
