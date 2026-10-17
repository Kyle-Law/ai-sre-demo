# 00 · Prerequisites

**Goal:** tools installed, accounts ready, `demo.env` filled in, and this repo pushed to your own
GitHub so ArgoCD (step 04) has something to deploy from.

## Tools

| Tool | Why | Install |
|---|---|---|
| Docker Desktop | runs the kind node. Settings → Resources: **4 CPU, 8 GB RAM** (6 GB minimum) | docker.com |
| `kind` | Kubernetes-in-Docker cluster (step 01) | `brew install kind` |
| `kubectl` | talk to the cluster | `brew install kubectl` |
| `helm` | install Cilium (step 02) | `brew install helm` |
| `gh` | branch protection (step 10) | `brew install gh` |
| `python3` 3.10+ | agent (step 11), scenarios (step 12) | preinstalled / `brew install python` |

## Accounts

| Account | Used from | Notes |
|---|---|---|
| GitHub | step 04 (ArgoCD pulls), step 10 (guardrails), step 11 (agent PRs) | A **public** repo you own: ArgoCD needs no credentials and branch protection is free |
| Jira Cloud | step 08 (alert bridge), step 11 (agent) | Free `*.atlassian.net` site, a project (any key, e.g. `INC` or `SUP`) with a **Task** issue type, an API token |
| Anthropic | step 11 | API key for the agent's model calls |

## Configure

```bash
cp demo.env.example demo.env && chmod 600 demo.env   # git-ignored; fill it in
./00-prereqs/configure-repo.sh                       # repo URL, Grafana URL, CODEOWNERS
git add -A && git commit -m "chore: configure demo repo" && git push
```

`demo.env` is read by every step's scripts through `lib/common.sh`. You can fill in the Jira values
later, before step 08.

**Why push first?** From step 05 on, ArgoCD deploys from *GitHub*, not from your working copy. Any
change under a step's `manifests/` or `values.yaml` only takes effect after `git push`.

## How the steps work

Every step folder has:

- `README.md`: what the step teaches, what to run, what to look at
- `run.sh`: does the step (`make step-NN`)
- `verify.sh`: proves it worked (`make verify-NN`)

Steps 05–09 each add **one ArgoCD Application**, so you watch GitOps deploy the platform piece by
piece. `make up` runs steps 01–09 in order; `make down` deletes the cluster.

**Next:** [01 · kind cluster](../01-kind-cluster/)
