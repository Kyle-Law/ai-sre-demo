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
| `selftest` fails on Kubernetes | Token expired, so re-run `generate-agent-kubeconfig.sh`. Or 6443 is blocked, or the VM IP isn't in the k3s cert (`--tls-san`) |
| `selftest` RBAC row FAILs | The `ai-sre` ArgoCD app isn't synced, or `shop`/`argocd` namespaces were missing when it synced. Hit Refresh/Sync on `ai-sre` |
| Jira 400 on transition | The transition name differs. Check `audit.jsonl` for `jira_transition_unavailable` (lists available names) and set `JIRA_TRANSITION_*` |
| Jira search 410/404 | Jira Cloud removed the old search API. The agent uses `/rest/api/3/search/jql`, so self-hosted Jira Data Center would need a change in `jira.py` |
| GitHub 403 on PR | The token lacks Pull requests: write, or the org blocks fine-grained PATs |
| GitHub 422 "Reviews may only be requested from collaborators" | Fix `GITHUB_REVIEWERS` (non-fatal; logged) |
| Agent re-opened a PR for an old ticket | The state DB was deleted. Tickets with an entry in `/var/lib/ai-sre-agent/state.db` are never re-processed |
| Want to replay a ticket | `sudo sqlite3 /var/lib/ai-sre-agent/state.db "delete from incidents where key='INC-3'"` |

## Scenarios

| Problem | Check |
|---|---|
| `expected exactly 1 match` | A previous scenario is still active or `apps/shop` was edited by hand. Run `python3 scenarios/demo.py reset` |
| `demo-baseline not found` | Run `python3 scenarios/demo.py baseline` once on a known-good main |
| Push rejected | Branch protection with `enforce_admins=true`. The demo operator must be an admin, or inject via a PR |
| 01 OOM doesn't trigger | The node has swap or a very old kernel. Check `kubectl -n shop describe pod`. The app loads ~96 MB at start, so the 64Mi limit must be hit |
| 06 doesn't trigger | Needs an admin kubeconfig. The agent's kubeconfig can't cordon, by design |
