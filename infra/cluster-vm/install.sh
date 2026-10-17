#!/usr/bin/env bash
# Cluster VM bootstrap: k3s + ArgoCD + secrets + app-of-apps.
# Run on the cluster VM (Ubuntu 22.04/24.04, 4 vCPU / 8 GB recommended):
#   sudo ./infra/cluster-vm/install.sh
# Idempotent: safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/../.."
# shellcheck disable=SC1091
source ./demo.env

: "${CLUSTER_VM_IP:?}" "${GITHUB_REPO:?}" "${ARGOCD_VERSION:?}"
: "${GRAFANA_ADMIN_PASSWORD:?}" "${JIRA_BASE_URL:?}" "${JIRA_EMAIL:?}" "${JIRA_API_TOKEN:?}" "${JIRA_PROJECT_KEY:?}"
REPO_URL="https://github.com/${GITHUB_REPO}.git"
TARGET_USER="${SUDO_USER:-$(whoami)}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

if grep -q 'YOUR_GITHUB_ORG' bootstrap/root-app.yaml; then
  echo "Run ./scripts/configure-repo.sh and push to GitHub first." >&2
  exit 1
fi

step "Installing k3s"
if ! command -v k3s >/dev/null; then
  curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server --tls-san ${CLUSTER_VM_IP} --disable traefik --write-kubeconfig-mode 600" sh -
fi
mkdir -p "${TARGET_HOME}/.kube"
cp /etc/rancher/k3s/k3s.yaml "${TARGET_HOME}/.kube/config"
chown -R "${TARGET_USER}:" "${TARGET_HOME}/.kube"
chmod 600 "${TARGET_HOME}/.kube/config"
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
until kubectl get nodes 2>/dev/null | grep -q ' Ready'; do sleep 3; done
kubectl get nodes -o wide

step "Installing ArgoCD ${ARGOCD_VERSION}"
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd --server-side --force-conflicts \
  -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml"
# Poll git every 30s instead of 3m so merged PRs roll out quickly in the demo.
kubectl -n argocd patch configmap argocd-cm --type merge -p '{"data":{"timeout.reconciliation":"30s"}}'
kubectl -n argocd patch svc argocd-server --type merge \
  -p '{"spec":{"type":"NodePort","ports":[{"name":"https","port":443,"targetPort":8080,"nodePort":30443,"protocol":"TCP"}]}}'
kubectl -n argocd rollout status deploy/argocd-repo-server --timeout=300s
kubectl -n argocd rollout restart deploy/argocd-repo-server
kubectl -n argocd rollout restart statefulset/argocd-application-controller

step "Creating secrets (never stored in git)"
for ns in monitoring ai-sre shop; do
  kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f -
done
kubectl -n monitoring create secret generic grafana-admin \
  --from-literal=admin-user="${GRAFANA_ADMIN_USER:-admin}" \
  --from-literal=admin-password="${GRAFANA_ADMIN_PASSWORD}" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n ai-sre create secret generic jira-credentials \
  --from-literal=JIRA_BASE_URL="${JIRA_BASE_URL}" \
  --from-literal=JIRA_EMAIL="${JIRA_EMAIL}" \
  --from-literal=JIRA_API_TOKEN="${JIRA_API_TOKEN}" \
  --from-literal=JIRA_PROJECT_KEY="${JIRA_PROJECT_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -
if [[ -n "${ARGOCD_REPO_READ_TOKEN:-}" ]]; then
  kubectl -n argocd create secret generic demo-repo \
    --from-literal=type=git --from-literal=url="${REPO_URL}" \
    --from-literal=username=git --from-literal=password="${ARGOCD_REPO_READ_TOKEN}" \
    --dry-run=client -o yaml | kubectl label --local -f - argocd.argoproj.io/secret-type=repository -o yaml \
    | kubectl apply -f -
fi

step "Bootstrapping app-of-apps from ${REPO_URL}"
kubectl apply -f bootstrap/root-app.yaml

step "Waiting for applications (monitoring can take ~5 minutes)"
for app in monitoring monitoring-config ai-sre shop; do
  for _ in $(seq 1 90); do
    status=$(kubectl -n argocd get application "$app" -o jsonpath='{.status.sync.status}/{.status.health.status}' 2>/dev/null || true)
    [[ "$status" == "Synced/Healthy" ]] && break
    sleep 10
  done
  printf '  %-18s %s\n' "$app" "${status:-unknown}"
done

ARGO_PW=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)
cat <<EOF

Cluster ready.
  ArgoCD : https://${CLUSTER_VM_IP}:30443   (admin / ${ARGO_PW})
  Grafana: http://${CLUSTER_VM_IP}:30300    (${GRAFANA_ADMIN_USER:-admin} / from demo.env)
  App    : kubectl -n shop port-forward svc/checkout 9898:80

Next steps (on this VM):
  ./scripts/verify-platform.sh
  ./scripts/create-grafana-token.sh                  # -> GRAFANA_TOKEN for the agent
  ./scripts/generate-agent-kubeconfig.sh --out agent.kubeconfig
  KUBECONFIG=agent.kubeconfig ./scripts/verify-rbac.sh
  scp agent.kubeconfig <agent-vm>:/tmp/
EOF
