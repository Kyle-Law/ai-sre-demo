# Security model

**Principle:** the agent has *read-only eyes* and *git-only hands*. Every change to the cluster
passes through a human-reviewed pull request and is applied by ArgoCD, never by the agent.

## Trust boundaries

| Actor | Can | Cannot |
|---|---|---|
| AI agent (K8s) | get/list/watch workloads, pods, logs, events, nodes, metrics; ConfigMaps in `shop`; ArgoCD Applications | any write; Secrets; exec / attach / port-forward; token requests; impersonation; ConfigMaps outside `shop` |
| AI agent (Grafana) | PromQL queries, read alert state (Viewer) | edit rules, dashboards, contact points |
| AI agent (GitHub App) | create branches, commit, open PRs on the one repo it's installed on | merge (branch protection), approve own PR, bypass checks, admin settings, any other repo |
| AI agent (Jira) | comment, transition, add labels on project tickets | anything outside the project's permission scheme |
| Alert bridge | create tickets / comment in one Jira project | read cluster state (no ServiceAccount token mounted) |
| Human reviewer | approve and merge | — |
| ArgoCD (`shop` project) | apply `06-demo-app/manifests` into namespace `shop` | create RBAC, Secrets, ServiceAccounts or cluster-scoped objects (except the `shop` Namespace) |

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
| Agent kubeconfig (bound SA token) | `agent.kubeconfig` (0600) | `--duration` (default 48h) |
| Grafana Viewer token | `agent.env` | 7 days |
| GitHub App private key | `github-app.pem` (0600) | until revoked in the App settings; it only mints tokens |
| GitHub App installation token | agent memory only | 1 hour, one repo, Contents + Pull requests |
| Jira API token (bot) | `agent.env`, plus a K8s Secret for the bridge | per Atlassian policy |
| Anthropic API key | `agent.env` | rotate after the demo |
| Grafana admin password | K8s Secret `monitoring/grafana-admin` | — |

Nothing above is committed to git (`.gitignore` covers `demo.env`, `*.kubeconfig`, `agent.env`, `*.pem`).

**Local-demo caveat:** the agent runs as your macOS user, so OS-level isolation from your admin
kubeconfig is not enforced; `11-agent/run.sh` only makes sure the agent *process* is handed
`agent.kubeconfig` and never your `KUBECONFIG`. In production, run the agent on its own host or pod
with only its own credentials mounted.

## In-cluster mode (step 12)

The local agent holds every credential in one process. In-cluster mode splits it:

| Identity | Runs | Holds | Kubernetes permissions |
|---|---|---|---|
| `agent-controller` (ns `ai-sre-agent`) | deterministic code: polling, state, validation, all writes | Jira token, GitHub App key, model key | AgentSessions in its namespace; create Jobs and read their logs in `ai-sre`; the read-only roles for verification. No Secrets, no pods/deployments, nothing in `shop` |
| `ai-sre-agent` (ns `ai-sre`), per-ticket Job | the LLM investigation | model key, Grafana Viewer token | the read-only roles from step 09; cannot create anything |

A ValidatingAdmissionPolicy pins every Job in `ai-sre` to that ServiceAccount, the agent image, the
`investigator-credentials` Secret and emptyDir volumes, so the controller's right to create Jobs
can't be turned into running something else. Both identities tolerate a cordoned node so the agent
still works during the incident it's investigating.

Trade-off: the agent now runs inside the cluster it diagnoses. If the cluster can't run pods at all,
fall back to the local agent (step 11), which watches from outside.

## Data sent to the model

Pod and event metadata, container logs (truncated), metric values, repo file contents and ticket
text are sent to the Anthropic API during diagnosis. Secrets are never read. In a real environment,
review log contents for PII and use a dedicated API workspace with appropriate data retention.

## Audit trail

- **Jira**: human-readable timeline: pickup, diagnosis with every command run, PR, reviews, merge,
  sync, verification, MTTR.
- **Git**: the PR conversation, the merge commit, and `incidents/<KEY>.md`.
- **ArgoCD**: sync history with revisions.
- **Agent audit log** (`.agent/audit.jsonl`): every tool call with input and truncated output, every
  external write, every state transition.

## Going beyond the demo

- Keep the GitHub App key in a secret manager or HSM instead of a file.
- Issue the kubeconfig through your identity provider or an external secret store, rotated automatically.
- Ship `audit.jsonl` to your SIEM.
- Add an OPA/Kyverno admission policy as one more gate behind ArgoCD.
- Use separate agent identities per environment or namespace.
