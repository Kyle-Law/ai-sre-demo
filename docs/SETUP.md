# Setup guide

Budget about an hour the first time. Everything runs on your laptop: a local **kind** cluster for
the platform, and the agent as a local process with its own read-only kubeconfig. Use a dedicated
repo and throwaway credentials.

## 0. What you need

| Item | Notes |
|---|---|
| **Docker Desktop** | Settings → Resources: **4 CPU, 8 GB RAM** (6 GB minimum). Runs the kind node: ArgoCD, Prometheus, Grafana, the alert bridge and the demo app. |
| **CLI tools** | `kind`, `kubectl`, `git`, `python3` (3.10+), `gh` (logged in as you). `brew install kind kubectl gh` |
| **GitHub** | A **public** repo you own. The agent gets its own identity as a **GitHub App**; no second account or email. |
| **Jira Cloud** | Free site (`*.atlassian.net`), one project, an API token. |
| **Anthropic API key** | For the agent's model calls. |

**What talks to what**

| From → To | Port | Why |
|---|---|---|
| Agent (host) → kind API server | `127.0.0.1:<random>` | Kubernetes API (read-only token); the port is written into `agent.kubeconfig` |
| Agent (host) → Grafana | `localhost:30300` | PromQL + alert state (Viewer token) |
| Agent (host) → internet | 443 | api.anthropic.com, api.github.com, `*.atlassian.net` |
| kind node → internet | 443 | github.com, ghcr.io, prometheus-community.github.io, `*.atlassian.net` (bridge) |
| Your browser | `localhost:30443`, `localhost:30300` | ArgoCD and Grafana UIs |

Nothing pushes to the agent; it polls Jira, Grafana and GitHub.

## 1. GitHub repo

Public, so ArgoCD needs no credentials and branch protection is free on a personal account. For a
private repo, set `ARGOCD_REPO_READ_TOKEN` in `demo.env`; protection on private personal repos needs
GitHub Pro.

```bash
cp demo.env.example demo.env && chmod 600 demo.env    # git-ignored; fill in every value
./scripts/configure-repo.sh                           # writes repo URL, Grafana URL, CODEOWNERS
git add -A && git commit -m "chore: configure demo repo" && git push
```

## 2. The agent's GitHub identity: a GitHub App

GitHub does not let anyone approve their own PR, so the agent must not use your token. A GitHub App
gives it a separate identity (`<slug>[bot]`) that **you** can approve, with no second account.

```bash
make github-app        # python3 scripts/create-github-app.py
```

A browser page opens on GitHub with the App pre-filled (private, Contents + Pull requests write,
no webhook). Click **Create GitHub App**. The script saves the private key to `github-app.pem`
(0600, git-ignored) and prints three things to do:

1. **Install** the App on *only* this repo (link printed; choose "Only select repositories").
2. Put `GITHUB_AGENT_LOGIN=<slug>[bot]` in `demo.env`.
3. Put `GITHUB_APP_ID` and `GITHUB_APP_PRIVATE_KEY_PATH` in `agent.env` (step 6).

Then turn on the guardrails:

```bash
./scripts/github-setup.sh   # branch protection, required checks, AGENT_GITHUB_LOGIN variable, labels
```

The agent exchanges the key for a 1-hour installation token, narrowed to this one repo and to
Contents/Pull requests, and renews it automatically. The App cannot merge: branch protection
requires a CODEOWNER (you) to approve.

## 3. Jira Cloud

1. Create a project with the Kanban template, key **`INC`**.
2. Recommended: add an **In Review** status (To Do → In Progress → In Review → Done). Missing
   transitions are skipped and logged.
3. Create an API token at <https://id.atlassian.com/manage-profile/security/api-tokens>. Your own
   account works; a separate bot user makes the Jira history read better.
4. Put `JIRA_*` values in `demo.env` (the alert bridge creates tickets) and in `agent.env` (the
   agent comments and transitions).
5. Optional: a board filter `labels = ai-triage` to show the queue on screen.

## 4. Local cluster

Start Docker Desktop, then:

```bash
make cluster-up        # ./infra/kind/up.sh
make verify            # everything OK except the baseline tag (step 7)
```

This creates the kind cluster `ai-sre` (kubectl context `kind-ai-sre`), installs metrics-server and
ArgoCD (polling git every 30s), creates the Grafana admin and Jira Secrets outside git, and applies
the app-of-apps. ArgoCD then deploys monitoring, the alert rules, the agent RBAC, the bridge and the
`shop` app from your GitHub repo.

Check it:
- ArgoCD at <https://localhost:30443> (accept the self-signed cert): five apps, Synced/Healthy.
- Grafana at <http://localhost:30300> → Alerting → Alert rules: folder **AI SRE Demo**, 5 rules.
- `kubectl -n shop get pods`: `checkout` 2/2 Running.

`make cluster-down` deletes everything; `make cluster-up` rebuilds it in ~5 minutes.

## 5. Agent credentials

```bash
./scripts/create-grafana-token.sh       # prints GRAFANA_URL / GRAFANA_TOKEN for agent.env
make agent-kubeconfig                   # read-only agent.kubeconfig, 48h token
make verify-rbac                        # every line must PASS
```

The kubeconfig token expires, so re-run `make agent-kubeconfig` before each demo day.

## 6. Run the agent

```bash
cp agent/.env.example agent.env && chmod 600 agent.env && $EDITOR agent.env
#   ANTHROPIC_API_KEY, GRAFANA_TOKEN, JIRA_*, GITHUB_APP_ID, GITHUB_REPO,
#   GITHUB_REVIEWERS=<your github user>
make agent-selftest                     # connectivity + RBAC matrix, all PASS
DRY_RUN=true make agent                 # first run: investigates and prints, writes nothing
```

`scripts/run-agent.sh` installs the agent into `.venv` on first use, ignores any `KUBECONFIG` in
your shell (the agent only ever gets `agent.kubeconfig`), and keeps state and the audit log in
`.agent/`.

Useful commands:

```bash
tail -f .agent/audit.jsonl | jq .            # audit trail of every tool call
make agent-status                            # incidents and their timelines
./scripts/run-agent.sh diagnose INC-12       # investigate one ticket, print only
```

## 7. Baseline and rehearsal

```bash
python3 scenarios/demo.py baseline       # tags the known-good apps/shop as demo-baseline
python3 scenarios/demo.py inject 01-oomkilled
```

Scenario commits are pushed straight to `main` as you (the repo admin can bypass protection; the
App cannot). Within about 2 minutes a Jira ticket appears. With `DRY_RUN=true` the agent prints its
comments and the PR. When they look right, stop it and run `make agent`.

Reset between runs:

```bash
python3 scenarios/demo.py reset --uncordon
```

Close leftover tickets in Jira too: the agent ignores tickets it has handled, but a clean board
looks better.

## 8. Final checklist

- [ ] Docker Desktop running, `make verify` all OK
- [ ] `make verify-rbac` all PASS
- [ ] `make agent-selftest` all PASS
- [ ] Jira board empty, Grafana shows no firing alerts
- [ ] Agent kubeconfig expiry (file header) is after the demo
- [ ] A rehearsal of scenario 01 completed end to end without `DRY_RUN`
