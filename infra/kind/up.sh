#!/usr/bin/env bash
# Local kind cluster bootstrap: kind + metrics-server + ArgoCD + secrets + app-of-apps.
# Needs Docker (Docker Desktop: 4 CPU / 8 GB recommended), kind and kubectl.
#   ./infra/kind/up.sh          (or: make cluster-up)
# Idempotent: safe to re-run. Tear down with: make cluster-down
# DEMO_ENV=path/to/other.env overrides ./demo.env.
set -euo pipefail
cd "$(dirname "$0")/../.."
# shellcheck disable=SC1090
source "${DEMO_ENV:-./demo.env}"

: "${GITHUB_REPO:?}" "${ARGOCD_VERSION:?}"
: "${GRAFANA_ADMIN_PASSWORD:?}" "${JIRA_BASE_URL:?}" "${JIRA_EMAIL:?}" "${JIRA_API_TOKEN:?}" "${JIRA_PROJECT_KEY:?}"
CLUSTER="${KIND_CLUSTER_NAME:-ai-sre}"
METRICS_SERVER_VERSION="${METRICS_SERVER_VERSION:-v0.9.0}"
REPO_URL="https://github.com/${GITHUB_REPO}.git"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

if grep -q 'YOUR_GITHUB_ORG' bootstrap/root-app.yaml; then
  echo "Run ./scripts/configure-repo.sh and push to GitHub first." >&2
  exit 1
fi
for bin in docker kind kubectl; do
  command -v "$bin" >/dev/null || { echo "$bin not found (brew install $bin)" >&2; exit 1; }
done
docker info >/dev/null 2>&1 || { echo "Docker is not running - start Docker Desktop first." >&2; exit 1; }
MEM_GB=$(( $(docker info --format '{{.MemTotal}}') / 1024 / 1024 / 1024 ))
(( MEM_GB >= 6 )) || echo "WARNING: Docker has ${MEM_GB} GB RAM; Prometheus + ArgoCD want ~6 GB (Docker Desktop > Settings > Resources)." >&2

step "kind cluster '${CLUSTER}'"
if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  kind create cluster --name "$CLUSTER" --config infra/kind/cluster.yaml --wait 120s
fi
kubectl config use-context "kind-${CLUSTER}" >/dev/null
kubectl get nodes -o wide

step "metrics-server ${METRICS_SERVER_VERSION} (for kubectl top)"
kubectl apply -f "https://github.com/kubernetes-sigs/metrics-server/releases/download/${METRICS_SERVER_VERSION}/components.yaml" >/dev/null
# kind kubelets serve self-signed certs.
if ! kubectl -n kube-system get deploy metrics-server -o jsonpath='{.spec.template.spec.containers[0].args}' | grep -q kubelet-insecure-tls; then
  kubectl -n kube-system patch deploy metrics-server --type json \
    -p '[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
fi

step "Installing ArgoCD ${ARGOCD_VERSION}"
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd --server-side --force-conflicts \
  -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml" >/dev/null
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

Cluster ready (kubectl context kind-${CLUSTER}).
  ArgoCD : https://localhost:30443   (admin / ${ARGO_PW})
  Grafana: http://localhost:30300    (${GRAFANA_ADMIN_USER:-admin} / from demo.env)
  App    : kubectl -n shop port-forward svc/checkout 9898:80

Next steps:
  make verify                    # platform health check
  ./scripts/create-grafana-token.sh   # -> GRAFANA_TOKEN in agent.env
  make agent-kubeconfig verify-rbac
  make agent-selftest
EOF
