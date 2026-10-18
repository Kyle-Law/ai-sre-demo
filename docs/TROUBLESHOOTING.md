# Troubleshooting

## Alerting / tickets

| Problem | Check |
|---|---|
| Rules missing in Grafana | `kubectl -n monitoring get cm -l grafana_alert=1`; Grafana sidecar logs: `kubectl -n monitoring logs deploy/kps-grafana -c grafana-sc-alerts` |
| Rule in "Error" state | Explore → run the rule's PromQL. Datasource UID must be `prometheus` (`grafana.sidecar.datasources.uid`) |
| Alert firing, no ticket | `kubectl -n ai-sre logs deploy/alert-bridge`. 401 means a bad Jira token; 400 usually means the issue type doesn't exist (set `JIRA_ISSUE_TYPE` in the bridge Deployment) |
| Bridge not reachable from Grafana | The NetworkPolicy only allows the `monitoring` namespace. Check the namespace has the label `kubernetes.io/metadata.name=monitoring` |
| Duplicate tickets | The bridge dedupes on `fp-<fingerprint>` and correlates on `wl-<ns>-<workload>` labels among *open* tickets; closed tickets don't count |

## Agent

| Problem | Check |
|---|---|
| `make verify-11` says Kubernetes is checked in the cluster | Expected: the agent's kubectl only runs in its pod. Use `make verify-12 ARGS=--selftest` |
| `selftest` RBAC row FAILs | The `agent-access` ArgoCD app isn't synced, or `shop`/`argocd` namespaces were missing when it synced (steps 04 and 06 come first). Hit Refresh/Sync on `agent-access` |
| Jira 400 on transition | The transition name differs. Check `audit.jsonl` for `jira_transition_unavailable` (lists available names) and set `JIRA_TRANSITION_*` |
| Jira search 410/404 | Jira Cloud removed the old search API. The agent uses `/rest/api/3/search/jql`, so self-hosted Jira Data Center would need a change in `jira.py` |
| GitHub App 404 on `/repos/.../installation` | The App isn't installed on the repo: `https://github.com/apps/<slug>/installations/new` |
| GitHub 401 "could not be decoded" / JWT errors | Wrong `GITHUB_APP_ID` for the key, or the Mac clock is off |
| GitHub 403 on PR | The App lacks Contents or Pull requests write (App settings → Permissions), or the installation wasn't updated after a permission change |
| GitHub 422 "Reviews may only be requested from collaborators" | Fix `GITHUB_REVIEWERS` (non-fatal; logged) |
| Agent re-opened a PR for an old ticket | Its AgentSession was deleted. Tickets with an AgentSession are never re-processed |
| Want to replay a ticket | `kubectl -n ai-sre-agent delete agentsession sup-3` |

## Scenarios

| Problem | Check |
|---|---|
| Scenario pushed but pods unchanged, `shop` OutOfSync | An earlier sync of an *invalid* commit is still retrying (ArgoCD → shop → sync status, or `kubectl -n argocd get app shop -o jsonpath='{.status.operationState.operation.sync.revision}'`). While it runs, newer commits aren't applied. Terminate it: ArgoCD UI → shop → **Terminate**, or `kubectl -n argocd patch app shop --type merge -p '{"status":{"operationState":{"phase":"Terminating"}}}'` |
| `expected exactly 1 match` | A previous scenario is still active or `06-demo-app/manifests` was edited by hand. Run `make reset` |
| `demo-baseline not found` | Run `make baseline` once on a known-good main |
| Push rejected | Branch protection with `enforce_admins=true`. The demo operator must be an admin, or inject via a PR |
| 01 OOM doesn't trigger | The node has swap or a very old kernel. Check `kubectl -n shop describe pod`. The app loads ~96 MB at start, so the 64Mi limit must be hit |
| 06 doesn't trigger | Needs the admin `kind-ai-sre` context. The agent's ServiceAccount can't cordon, by design |

## Local cluster (kind)

| Problem | Check |
|---|---|
| `make step-01`: port 30300/30443 already allocated | Another kind cluster or service uses it: `docker ps`, or `make down` and retry |
| Pods `Pending` / Prometheus OOMKilled right after setup | Docker Desktop memory too low; give it 8 GB |
| `kubectl top` fails | metrics-server still starting (~1 min): `kubectl -n kube-system get deploy metrics-server` |
| Laptop slept, alerts went stale | `docker restart ai-sre-control-plane`, wait for pods, `make verify-14` |
