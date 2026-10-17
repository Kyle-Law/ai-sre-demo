# 09 · Agent access: read-only eyes

**Goal:** give the AI agent an identity that can see everything it needs to diagnose an incident,
and nothing that lets it change the cluster. Then prove it, line by line.

## Concepts

- **ServiceAccount + RBAC** ([manifests/rbac.yaml](manifests/rbac.yaml)):
  - cluster-wide `get/list/watch` on workloads, pods, logs, events, nodes and metrics
  - ConfigMaps only in `shop`; ArgoCD Applications only in `argocd` (to check sync status)
  - **no** writes, **no** Secrets, **no** `exec`/`attach`/`port-forward`, **no** token requests or
    impersonation
- **Bound ServiceAccount tokens**: [generate-agent-kubeconfig.sh](generate-agent-kubeconfig.sh) uses
  `kubectl create token --duration 48h`. The token expires on its own and dies with the
  ServiceAccount. Nothing long-lived sits on disk. Re-run `make step-09` to rotate.
- **Proving it, not claiming it**: [verify-rbac.sh](verify-rbac.sh) runs `kubectl auth can-i` for
  every allow and deny, then tries a real `delete pod` (server-side dry run) that the API server
  must reject. It's a good moment to show live.
- **Grafana access**: [create-grafana-token.sh](create-grafana-token.sh) creates a Grafana service
  account with the **Viewer** role. The agent can run PromQL and read alert state, but can't edit
  rules.
- **Defence in depth**: the agent's own kubectl wrapper (step 11) also refuses write verbs and
  Secret reads before calling the API. RBAC is the layer that holds if that check were bypassed.

## Run

```bash
make step-09                                 # RBAC via ArgoCD + agent.kubeconfig
make verify-09                               # 23 checks + a live delete that must fail
./09-agent-access/create-grafana-token.sh    # prints GRAFANA_URL / GRAFANA_TOKEN for agent.env
```

## Look around

```bash
KUBECONFIG=agent.kubeconfig kubectl get pods -A          # works
KUBECONFIG=agent.kubeconfig kubectl -n shop get secrets  # Forbidden
KUBECONFIG=agent.kubeconfig kubectl auth can-i --list -n shop
head -1 agent.kubeconfig                                 # token expiry
```

**Next:** [10 · GitHub guardrails](../10-github-guardrails/)
