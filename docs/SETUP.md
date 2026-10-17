# Setup guide

Budget about 90 minutes the first time. Everything here is a demo environment:
use throwaway accounts, a dedicated repo and fresh VMs.

## 0. What you need

| Item | Notes |
|---|---|
| **Cluster VM** | Ubuntu 22.04/24.04, 4 vCPU, 8 GB RAM, 40 GB disk. Runs k3s, ArgoCD, Prometheus, Grafana, the alert bridge and the demo app. |
| **Agent VM** | Ubuntu 22.04/24.04, 1 vCPU, 1–2 GB RAM. Runs only the agent. |
| **GitHub** | A free **organization** (e.g. `acme-sre-demo`) owning a **public** repo, plus a second GitHub account for the agent bot. |
| **Jira Cloud** | Free site (`*.atlassian.net`), one project, one bot account. |
| **Anthropic API key** | For the agent's model calls. |
| Workstation | `git`, `python3`, `gh` CLI (logged in as the human admin). |

**Network**

| From → To | Port | Why |
|---|---|---|
| Agent VM → Cluster VM | 6443/tcp | Kubernetes API (read-only token) |
| Agent VM → Cluster VM | 30300/tcp | Grafana API (PromQL + alert state, Viewer token) |
| Agent VM → internet | 443 | api.anthropic.com, api.github.com, `*.atlassian.net` |
| Cluster VM → internet | 443 | github.com, ghcr.io, prometheus-community.github.io, `*.atlassian.net` (bridge) |
| You → Cluster VM | 30443, 30300 | ArgoCD and Grafana UIs |

Nothing needs to reach the agent VM inbound. The agent polls; nothing pushes to it.

## 1. GitHub

1. Create the org and a **public** repo `ai-sre-demo`, and push this code to `main`.
   A public repo keeps ArgoCD config simple and makes branch protection free. For a private repo,
   set `ARGOCD_REPO_READ_TOKEN` in `demo.env`, and note that protection on private repos needs a paid plan.
2. Create the **bot account** (e.g. `acme-ai-sre-bot`), invite it to the org, and give it **Write** on the repo.
   Do not give it Admin or Maintain.
3. While logged in as the bot, create a **fine-grained personal access token**:
   - Resource owner: the org
   - Repository access: only `ai-sre-demo`
   - Permissions: **Contents: Read and write**, **Pull requests: Read and write** (Metadata: read is automatic)
   - Expiry: 7–30 days

   The org may need to allow fine-grained tokens under Settings → Personal access tokens.
   If you can't use an org, a classic PAT with `public_repo` scope on the bot account also works.

   > Why a separate account? GitHub does not let someone approve their own PR. If the agent
   > used your token, you couldn't be the human approver. The separation is the point of the demo.

## 2. Jira Cloud

1. Create a project with the Kanban template, key **`INC`**.
2. Recommended: add an **In Review** status to the workflow (To Do → In Progress → In Review → Done).
   If a transition name doesn't exist, the agent skips it and logs that.
3. Create a bot user (e.g. `ai-sre-bot@yourdomain`) with access to the project. Log in as the bot
   and create an API token at <https://id.atlassian.com/manage-profile/security/api-tokens>.
4. The same token can serve the alert bridge (creates tickets) and the agent (comments,
   transitions, labels). For a stronger demo, use two accounts.
5. Optional: create a board filter `labels = ai-triage` to show the queue on screen.

## 3. Configure the repo (workstation)

```bash
cp demo.env.example demo.env      # git-ignored; fill in every value
./scripts/configure-repo.sh       # writes your repo URL, Grafana URL and CODEOWNERS
git add -A && git commit -m "chore: configure demo repo" && git push
./scripts/github-setup.sh         # branch protection, required checks, AGENT_GITHUB_LOGIN, labels
```

Open a trivial PR to make sure `validate-manifests` and `agent-scope-guard` run. Branch protection
requires those two check names.

## 4. Cluster VM

```bash
git clone https://github.com/<org>/ai-sre-demo.git && cd ai-sre-demo
cp /path/to/demo.env .            # same file as on your workstation
sudo ./infra/cluster-vm/install.sh
./scripts/verify-platform.sh      # everything should be OK except the baseline tag (step 7)
```

The install script sets up k3s with the VM IP in the API certificate, Traefik disabled, and ArgoCD
polling git every 30s. It creates the Grafana admin and Jira Secrets outside git, then applies the
app-of-apps. ArgoCD then deploys monitoring, the alert rules, the agent RBAC, the bridge and the
`shop` app.

Check it:
- ArgoCD at `https://<CLUSTER_VM_IP>:30443`: five apps, all Synced/Healthy.
- Grafana at `http://<CLUSTER_VM_IP>:30300` → Alerting → Alert rules: folder **AI SRE Demo** with 5 rules.
- `kubectl -n shop get pods`: `checkout` shows 2/2 Running.

## 5. Agent credentials (cluster VM)

```bash
./scripts/create-grafana-token.sh                       # prints GRAFANA_URL / GRAFANA_TOKEN
./scripts/generate-agent-kubeconfig.sh --out agent.kubeconfig --duration 48h
KUBECONFIG=agent.kubeconfig ./scripts/verify-rbac.sh    # every line must PASS
scp agent.kubeconfig <agent-vm>:/tmp/
```

The token expires, so re-run `generate-agent-kubeconfig.sh` before each demo day and copy the file
again. Rotation is itself a good talking point.

## 6. Agent VM

```bash
git clone https://github.com/<org>/ai-sre-demo.git && cd ai-sre-demo
cp agent/.env.example /tmp/agent.env && $EDITOR /tmp/agent.env
#   ANTHROPIC_API_KEY, GRAFANA_URL/TOKEN, JIRA_*, GITHUB_TOKEN (bot), GITHUB_REPO,
#   GITHUB_REVIEWERS=<your github user>
#   First run: DRY_RUN=true (agent investigates and prints, but writes nothing)
sudo ./infra/agent-vm/setup.sh /tmp/agent.kubeconfig /tmp/agent.env
shred -u /tmp/agent.env /tmp/agent.kubeconfig
```

`setup.sh` runs `ai-sre-agent selftest` and only starts the service if connectivity works and the
RBAC matrix holds (reads allowed, writes and Secrets denied).

Useful commands:

```bash
journalctl -fu ai-sre-agent                          # live agent log
sudo tail -f /var/log/ai-sre-agent/audit.jsonl | jq . # audit trail of every tool call
sudo ai-sre-agent status                             # incidents and their timelines
sudo ai-sre-agent diagnose INC-12                    # investigate one ticket, print only
```

## 7. Baseline and rehearsal

From your workstation (or anywhere with push rights to `main`):

```bash
python3 scenarios/demo.py baseline       # tags the known-good apps/shop as demo-baseline
python3 scenarios/demo.py inject 01-oomkilled
```

Within about 2 minutes, a Jira ticket appears. With `DRY_RUN=true`, the agent prints its comments
and the PR in `journalctl`. When you're happy with them, set `DRY_RUN=false` in
`/etc/ai-sre-agent/agent.env` and run `sudo systemctl restart ai-sre-agent`.

Reset between runs:

```bash
python3 scenarios/demo.py reset --uncordon
```

Close leftover tickets in Jira as well: the agent ignores tickets it has already handled, but a
clean board looks better.

## 8. Final checklist

- [ ] `./scripts/verify-platform.sh` is all OK
- [ ] `KUBECONFIG=agent.kubeconfig ./scripts/verify-rbac.sh` is all PASS
- [ ] `sudo ai-sre-agent selftest` is all PASS
- [ ] Jira board is empty, Grafana shows no firing alerts
- [ ] The agent token expiry is after the demo time
- [ ] A rehearsal of scenario 01 completed end to end with `DRY_RUN=false`
