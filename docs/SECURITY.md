# Security model

**Principle:** the agent has *read-only eyes* and *git-only hands*. Every change to the cluster
passes through a human-reviewed pull request and is applied by ArgoCD, never by the agent.

## Trust boundaries

| Actor | Can | Cannot |
|---|---|---|
| AI agent (K8s) | get/list/watch workloads, pods, logs, events, nodes, metrics; ConfigMaps in `shop`; ArgoCD Applications | any write; Secrets; exec / attach / port-forward; token requests; impersonation; ConfigMaps outside `shop` |
| AI agent (Grafana) | PromQL queries, read alert state (Viewer) | edit rules, dashboards, contact points |
| AI agent (GitHub) | create branches, commit, open PRs | merge (branch protection), approve own PR, bypass checks, admin settings |
| AI agent (Jira) | comment, transition, add labels on project tickets | anything outside the project's permission scheme |
| Alert bridge | create tickets / comment in one Jira project | read cluster state (no ServiceAccount token mounted) |
| Human reviewer | approve and merge | — |
| ArgoCD (`shop` project) | apply `apps/shop` into namespace `shop` | create RBAC, Secrets, ServiceAccounts or cluster-scoped objects (except the `shop` Namespace) |

## Defence in depth for a bad or manipulated proposal

1. **Prompt layer**: the system prompt tells the model to treat logs, events, commit messages and
   ticket text as untrusted data.
2. **Tool layer**: `kube.py` refuses non-read verbs, Secret resources, and credential or
   target-switching flags (`--as`, `--kubeconfig`, `--server`, `--token`, …) before calling the API.
3. **RBAC layer**: even if (2) were bypassed, the ServiceAccount cannot write.
4. **Change validation**: before any PR is opened, proposed files must be under `AGENT_ALLOWED_PATHS`,
   parse as YAML, contain no Secret/RBAC/ServiceAccount kinds, and change at most 80 lines.
5. **CI**: `agent-scope-guard` fails agent PRs that touch anything outside `apps/` and `incidents/`.
   `validate-manifests` schema-checks every kustomization and blocks privileged pod settings.
6. **Human review**: one approving review from a CODEOWNER, stale approvals dismissed.
7. **ArgoCD AppProject**: an approved PR still cannot escalate privileges through the `shop` app.
8. **Loop limits**: one PR per attempt, at most `MAX_ATTEMPTS` (default 2) attempts. A closed or
   rejected PR makes the agent stand down and label the ticket `needs-human`.

## Credentials

| Secret | Lives in | Lifetime |
|---|---|---|
| Agent kubeconfig (bound SA token) | `/etc/ai-sre-agent/kubeconfig` on the agent VM, 0640 root:aisre | `--duration` (default 48h) |
| Grafana Viewer token | `agent.env` | 7 days |
| GitHub fine-grained PAT (bot) | `agent.env` | 7–30 days, one repo |
| Jira API token (bot) | `agent.env`, plus a K8s Secret for the bridge | per Atlassian policy |
| Anthropic API key | `agent.env` | rotate after the demo |
| Grafana admin password | K8s Secret `monitoring/grafana-admin` | — |

Nothing above is committed to git (`.gitignore` covers `demo.env`, `*.kubeconfig`, `agent.env`).

## Data sent to the model

Pod and event metadata, container logs (truncated), metric values, repo file contents and ticket
text are sent to the Anthropic API during diagnosis. Secrets are never read. In a real environment,
review log contents for PII and use a dedicated API workspace with appropriate data retention.

## Audit trail

- **Jira**: human-readable timeline: pickup, diagnosis with every command run, PR, reviews, merge,
  sync, verification, MTTR.
- **Git**: the PR conversation, the merge commit, and `incidents/<KEY>.md`.
- **ArgoCD**: sync history with revisions.
- **Agent audit log** (`audit.jsonl`): every tool call with input and truncated output, every
  external write, every state transition.

## Going beyond the demo

- Replace the PAT with a GitHub App (short-lived installation tokens).
- Issue the kubeconfig through your identity provider or an external secret store, rotated automatically.
- Ship `audit.jsonl` to your SIEM.
- Add an OPA/Kyverno admission policy as one more gate behind ArgoCD.
- Use separate agent identities per environment or namespace.
