#!/usr/bin/env bash
# Step 04: install ArgoCD and point it at your GitHub repo.
source "$(dirname "$0")/../lib/common.sh"
need_context
need GITHUB_REPO ARGOCD_VERSION
REPO_URL="https://github.com/${GITHUB_REPO}.git"

step "ArgoCD ${ARGOCD_VERSION}"
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd --server-side --force-conflicts \
  -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml" >/dev/null

step "Demo tuning"
# Poll git every 30s instead of 3m so merged PRs roll out quickly.
kubectl -n argocd patch configmap argocd-cm --type merge -p '{"data":{"timeout.reconciliation":"30s"}}'
# UI on https://localhost:30443 (port mapped in 01-kind-cluster/cluster.yaml).
kubectl -n argocd patch svc argocd-server --type merge \
  -p '{"spec":{"type":"NodePort","ports":[{"name":"https","port":443,"targetPort":8080,"nodePort":30443,"protocol":"TCP"}]}}'

if [[ -n "${ARGOCD_REPO_READ_TOKEN:-}" ]]; then
  step "Private repo credentials"
  kubectl -n argocd create secret generic demo-repo \
    --from-literal=type=git --from-literal=url="${REPO_URL}" \
    --from-literal=username=git --from-literal=password="${ARGOCD_REPO_READ_TOKEN}" \
    --dry-run=client -o yaml | kubectl label --local -f - argocd.argoproj.io/secret-type=repository -o yaml \
    | kubectl apply -f -
fi

step "Waiting for ArgoCD"
kubectl -n argocd rollout status deploy/argocd-repo-server --timeout=300s
# Pick up the new reconciliation interval.
kubectl -n argocd rollout restart deploy/argocd-repo-server statefulset/argocd-application-controller
kubectl -n argocd rollout status deploy/argocd-server --timeout=300s
kubectl -n argocd rollout status statefulset/argocd-application-controller --timeout=300s

ARGO_PW=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)
cat <<EOF

ArgoCD UI: https://localhost:30443   (admin / ${ARGO_PW})
No applications yet - steps 05-09 each add one.
Next: make verify-04, then make step-05
EOF
