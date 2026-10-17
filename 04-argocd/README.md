# 04 · ArgoCD

**Goal:** install the GitOps engine. From the next step on, nothing is `kubectl apply`'d by hand
except ArgoCD `Application` objects; ArgoCD pulls everything else from your GitHub repo.

## Concepts

- **GitOps**: git is the source of truth. ArgoCD keeps comparing what's in git with what's in the
  cluster, reports drift (`OutOfSync`), and with `automated` sync it fixes the drift.
- **Application**: "deploy *this path* of *this repo* into *this namespace*". Steps 05–09 each add one:

  | Step | Application | Source path |
  |---|---|---|
  | 05 | `monitoring` | Helm chart + [05-monitoring/values.yaml](../05-monitoring/values.yaml) |
  | 06 | `shop` | [06-demo-app/manifests](../06-demo-app/manifests) |
  | 07 | `alert-rules` | [07-alert-rules/manifests](../07-alert-rules/manifests) |
  | 08 | `jira-integration` | [08-jira-integration/manifests](../08-jira-integration/manifests) |
  | 09 | `agent-access` | [09-agent-access/manifests](../09-agent-access/manifests) |

- **AppProject**: a guardrail around Applications (allowed repos, namespaces and kinds). Step 06 adds a
  restricted one for the app the AI agent is allowed to change.
- **Why it matters here:** the agent never touches the cluster. It opens a PR; once a human merges
  it, *ArgoCD* applies the fix. `timeout.reconciliation: 30s` keeps that loop short for a live demo.

## Run

```bash
make step-04
make verify-04
```

Open <https://localhost:30443> (accept the self-signed certificate) and log in as `admin` with the
password the script prints. It's empty for now.

## Look around

```bash
kubectl -n argocd get pods
kubectl -n argocd get cm argocd-cm -o yaml | grep reconciliation
kubectl api-resources --api-group=argoproj.io      # Application, AppProject, ApplicationSet
```

**Next:** [05 · Monitoring](../05-monitoring/)
