# 09 · Agent access: read-only eyes

**Goal:** give the AI agent an identity that can see everything it needs to diagnose an incident,
and nothing that lets it change the cluster. Then prove it, line by line.

## Concepts

- **ServiceAccount + RBAC** ([manifests/rbac.yaml](manifests/rbac.yaml)):
  - cluster-wide `get/list/watch` on workloads, pods, logs, events, nodes and metrics
  - ConfigMaps only in `shop`; ArgoCD Applications only in `argocd` (to check sync status)
  - **no** writes, **no** Secrets, **no** `exec`/`attach`/`port-forward`, **no** token requests or
    impersonation
- **No credential to hand out**: the agent runs in the cluster (step 12) as this ServiceAccount.
  Kubernetes mounts a short-lived, auto-rotated token into its pods, so there's no kubeconfig to
  copy, store or expire. The token isn't mounted by default (`automountServiceAccountToken: false`);
  only the diagnosis Jobs opt in.
- **Proving it, not claiming it**: [verify-rbac.sh](verify-rbac.sh) impersonates the ServiceAccount
  (`kubectl --as=system:serviceaccount:ai-sre:ai-sre-agent`), runs `kubectl auth can-i` for every
  allow and deny, then tries a real `delete pod` (server-side dry run) that the API server must
  reject. It's a good moment to show live.
- **Grafana access**: [create-grafana-token.sh](create-grafana-token.sh) creates a Grafana service
  account with the **Viewer** role. The agent can run PromQL and read alert state, but can't edit
  rules.
- **Defence in depth**: the agent's own kubectl wrapper (step 11) also refuses write verbs and
  Secret reads before calling the API. RBAC is the layer that holds if that check were bypassed.

## Run

```bash
make step-09                                 # ServiceAccount + RBAC via ArgoCD
make verify-09                               # 23 checks + a live delete that must fail
./09-agent-access/create-grafana-token.sh    # prints GRAFANA_URL / GRAFANA_TOKEN for agent.env
```

## Look around

```bash
AS=system:serviceaccount:ai-sre:ai-sre-agent
kubectl --as=$AS get pods -A                 # works
kubectl --as=$AS -n shop get secrets         # Forbidden
kubectl auth can-i --list -n shop --as=$AS   # everything it may do in shop
```

**Next:** [10 · GitHub guardrails](../10-github-guardrails/)
