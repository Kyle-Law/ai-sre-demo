#!/usr/bin/env bash
#   ./12-agent-operator/verify.sh              # deployment, guardrails, RBAC
#   ./12-agent-operator/verify.sh --selftest   # + the agent's own selftest from inside the controller pod
source "$(dirname "$0")/../lib/common.sh"
need_context
CONTROLLER=system:serviceaccount:ai-sre-agent:agent-controller
INVESTIGATOR=system:serviceaccount:ai-sre:ai-sre-agent

watching_jira() {  # not grep -q: its early exit breaks the pipe, and pipefail reports that
  kubectl -n ai-sre-agent logs deploy/agent-controller | grep "watching Jira project" >/dev/null
}
can() { [[ "$(kubectl auth can-i "${@:2}" --as="$1" 2>/dev/null)" == yes ]]; }
cannot() { ! can "$@"; }
# Admission policy: even an admin can't start a Job in ai-sre that isn't the investigator.
rogue_job_denied() {
  local out
  out=$(kubectl -n ai-sre create job "rogue-$RANDOM" --image=busybox:1.36 --dry-run=server -- true 2>&1) && return 1
  grep -q "ai-sre-investigator-jobs" <<<"$out"
}

echo "Controller"
check "ArgoCD app 'agent-operator' Synced/Healthy" app_healthy agent-operator
check "agent-controller ready" kubectl -n ai-sre-agent rollout status deploy/agent-controller --timeout=5s
check "controller is watching Jira" watching_jira
check "AgentSession CRD served" kubectl -n ai-sre-agent get agentsessions
echo "Guardrails"
check "admission policy denies a rogue Job in ai-sre" rogue_job_denied
check "controller can create Jobs in ai-sre" can "$CONTROLLER" create jobs -n ai-sre
check "controller CANNOT read Secrets" cannot "$CONTROLLER" get secrets -n ai-sre
check "controller CANNOT create pods/deployments" cannot "$CONTROLLER" create deployments -n ai-sre
check "controller CANNOT touch the demo app" cannot "$CONTROLLER" patch deployments -n shop
check "investigator CANNOT create anything" cannot "$INVESTIGATOR" create jobs -n ai-sre
check "investigator Secret holds only model key + Grafana token" \
  bash -c "[[ \$(kubectl -n ai-sre get secret investigator-credentials -o jsonpath='{.data}' | python3 -c 'import sys,json; print(\",\".join(sorted(json.load(sys.stdin))))') == ANTHROPIC_API_KEY,GRAFANA_TOKEN ]]"
summary

if [[ "${1:-}" == "--selftest" ]]; then
  echo
  kubectl -n ai-sre-agent exec deploy/agent-controller -- ai-sre-agent selftest
fi
