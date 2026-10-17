#!/usr/bin/env bash
# Mint a short-lived, read-only kubeconfig for the AI agent from the
# ai-sre/ai-sre-agent ServiceAccount (RBAC in 09-agent-access/manifests/rbac.yaml).
#
# Run with an ADMIN kubeconfig (the kind-ai-sre context that step 01 selects):
#   ./09-agent-access/generate-agent-kubeconfig.sh --out agent.kubeconfig [--duration 48h] [--server https://HOST:PORT]
#
# The token is a bound ServiceAccount token: it expires (default 48h) and is
# revoked if the ServiceAccount is deleted. Re-run to rotate.
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=agent.kubeconfig
DURATION=48h
SERVER=""
NAMESPACE=ai-sre
SA=ai-sre-agent
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --duration) DURATION="$2"; shift 2 ;;
    --server) SERVER="$2"; shift 2 ;;
    *) echo "unknown arg $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$SERVER" ]]; then
  SERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
fi

kubectl -n "$NAMESPACE" get serviceaccount "$SA" >/dev/null \
  || { echo "ServiceAccount $NAMESPACE/$SA not found - is the agent-access ArgoCD app synced (make step-09)?" >&2; exit 1; }

CA_DATA=$(kubectl config view --raw --minify -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')
TOKEN=$(kubectl -n "$NAMESPACE" create token "$SA" --duration="$DURATION")
EXPIRES=$(date -u -d "+${DURATION%h} hours" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
  || date -u -v+"${DURATION%h}"H +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "in ${DURATION}")

umask 077
cat > "$OUT" <<EOF
# Read-only kubeconfig for the AI SRE agent. Token expires: ${EXPIRES}
apiVersion: v1
kind: Config
clusters:
  - name: demo
    cluster:
      server: ${SERVER}
      certificate-authority-data: ${CA_DATA}
users:
  - name: ai-sre-agent
    user:
      token: ${TOKEN}
contexts:
  - name: ai-sre-agent@demo
    context:
      cluster: demo
      user: ai-sre-agent
      namespace: shop
current-context: ai-sre-agent@demo
EOF

echo "Wrote $OUT (server ${SERVER}, expires ${EXPIRES})."
echo "Prove it is read-only:  KUBECONFIG=$OUT ./09-agent-access/verify-rbac.sh"
