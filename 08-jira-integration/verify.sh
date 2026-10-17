#!/usr/bin/env bash
#   ./08-jira-integration/verify.sh                    # cluster-side checks
#   ./08-jira-integration/verify.sh --send-test-alert  # + create and resolve one real Jira ticket
source "$(dirname "$0")/../lib/common.sh"
need_context
BRIDGE=http://alert-bridge.ai-sre.svc.cluster.local:8080

# One-shot pod in namespace $1 running a shell snippet $2.
pod_sh() {
  kubectl -n "$1" run "np-check-$RANDOM" --rm -i --restart=Never --quiet --image=busybox:1.36 \
    --timeout=90s --command -- sh -c "$2"
}
reachable_from() { pod_sh "$1" "wget -qO- -T 5 $BRIDGE/healthz"; }
blocked_from() { ! reachable_from "$1"; }
contact_point_loaded() { grafana_api /api/v1/provisioning/contact-points | grep -q jira-bridge-webhook; }
policy_routes_to_bridge() { grafana_api /api/v1/provisioning/policies | grep -q '"receiver":"jira-bridge"'; }
jira_auth_ok() {
  curl -fsS -u "${JIRA_EMAIL}:${JIRA_API_TOKEN}" "${JIRA_BASE_URL}/rest/api/3/project/${JIRA_PROJECT_KEY}" >/dev/null
}

echo "Alert bridge"
check "ArgoCD app 'jira-integration' Synced/Healthy" app_healthy jira-integration
check "alert-bridge ready" kubectl -n ai-sre rollout status deploy/alert-bridge --timeout=5s
check "Jira credentials work for project ${JIRA_PROJECT_KEY:-?} (from this machine)" jira_auth_ok
echo "Grafana routing"
check "contact point 'jira-bridge' loaded" contact_point_loaded
check "notification policy routes to jira-bridge" policy_routes_to_bridge
echo "NetworkPolicy (enforced by Cilium, step 02)"
check "monitoring namespace CAN reach the bridge" reachable_from monitoring
check "default namespace is BLOCKED" blocked_from default

if [[ "${1:-}" == "--send-test-alert" ]]; then
  echo "End-to-end"
  fp="bridge-test-$(date +%s)"
  alert() {  # alert <firing|resolved>
    printf '{"alerts":[{"status":"%s","fingerprint":"%s","labels":{"alertname":"BridgeTest","namespace":"shop","workload":"bridge-test","severity":"info","ai_triage":"true"},"annotations":{"summary":"Test alert from 08-jira-integration/verify.sh","description":"Safe to close."}}]}' "$1" "$fp"
  }
  check "firing test alert accepted (creates a ticket)" \
    pod_sh monitoring "wget -qO- -T 20 --header 'Content-Type: application/json' --post-data '$(alert firing)' $BRIDGE/grafana"
  check "resolved test alert accepted (comments on it)" \
    pod_sh monitoring "wget -qO- -T 20 --header 'Content-Type: application/json' --post-data '$(alert resolved)' $BRIDGE/grafana"
  info "Look for a 'BridgeTest' ticket in ${JIRA_BASE_URL}/jira/software/projects/${JIRA_PROJECT_KEY} and close it."
  info "Bridge log: kubectl -n ai-sre logs deploy/alert-bridge --tail=20"
fi
summary
