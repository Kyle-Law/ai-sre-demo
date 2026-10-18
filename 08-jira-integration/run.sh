#!/usr/bin/env bash
# Step 08: Grafana -> Jira alert bridge via ArgoCD.
source "$(dirname "$0")/../lib/common.sh"
need_context
need JIRA_BASE_URL JIRA_API_TOKEN JIRA_PROJECT_KEY
# A user's classic token needs JIRA_EMAIL; a service account's scoped token needs JIRA_API_URL instead.
[[ -n "${JIRA_EMAIL:-}" || -n "${JIRA_API_URL:-}" ]] || die "set JIRA_EMAIL (user token) or JIRA_API_URL (service account) in demo.env"
need_namespace monitoring 05
need_pushed 08-jira-integration

step "Jira credentials Secret (from demo.env, never in git)"
kubectl create namespace ai-sre --dry-run=client -o yaml | kubectl apply -f -
kubectl -n ai-sre create secret generic jira-credentials \
  --from-literal=JIRA_BASE_URL="${JIRA_BASE_URL}" \
  --from-literal=JIRA_EMAIL="${JIRA_EMAIL:-}" \
  --from-literal=JIRA_API_URL="${JIRA_API_URL:-}" \
  --from-literal=JIRA_API_TOKEN="${JIRA_API_TOKEN}" \
  --from-literal=JIRA_PROJECT_KEY="${JIRA_PROJECT_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -
# Pick up a changed Secret on re-runs.
kubectl -n ai-sre rollout restart deploy/alert-bridge 2>/dev/null || true

step "ArgoCD Application 'jira-integration'"
kubectl apply -f 08-jira-integration/application.yaml
wait_app jira-integration 300

cat <<EOF

Alerts from step 07 now route: Grafana -> alert-bridge -> Jira project ${JIRA_PROJECT_KEY}.
End-to-end test (creates and resolves one ticket):  ./08-jira-integration/verify.sh --send-test-alert
Next: make verify-08, then make step-09
EOF
