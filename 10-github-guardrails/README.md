# 10 · GitHub guardrails: git-only hands

**Goal:** the agent can propose changes as pull requests, but only a human can approve and merge
them, and CI rejects agent PRs that reach outside the demo app.

## Concepts

- **A GitHub App as the agent's identity**: GitHub won't let anyone approve their own PR, so the agent
  must not use your token. A GitHub App opens PRs as `<slug>[bot]`, which you *can* approve, with no
  second account or email. [create-github-app.py](create-github-app.py) creates it from a
  **manifest**: a local page posts the settings (private App, Contents + Pull requests write, no
  webhook) to GitHub, you click **Create**, and the script saves the private key to `github-app.pem`.
- **Short-lived tokens**: the agent (step 11) signs a JWT with that key and exchanges it for a
  **1-hour installation token**, narrowed to this one repo, and renews it automatically.
- **Branch protection** ([github-setup.sh](github-setup.sh)): `main` needs a PR, one approving review
  from a **CODEOWNER** (you, in [.github/CODEOWNERS](../.github/CODEOWNERS)), the two required
  checks, and stale approvals are dismissed. `enforce_admins` stays off so you, the admin, can push
  scenario commits straight to `main` (step 13). The App is not an admin.
- **CI scope guard** ([.github/workflows/pr-checks.yaml](../.github/workflows/pr-checks.yaml)):
  - `validate-manifests`: every kustomization renders and passes kubeconform; no privileged pods or
    RBAC/Secrets in the demo app
  - `agent-scope-guard`: if the PR author is `AGENT_GITHUB_LOGIN`, every changed file must be under
    `06-demo-app/manifests/` or `incidents/`

## Run

`gh` must act as the repo owner. If you have several gh accounts, prefix the commands with
`GH_TOKEN=$(gh auth token --user <owner>)`.

```bash
make step-10     # 1st run: creates the GitHub App (browser) and prints next steps
#   -> install the App on ONLY this repo (link printed)
#   -> demo.env:  GITHUB_AGENT_LOGIN=<slug>[bot]
make step-10     # 2nd run: branch protection, required checks, CI variable, labels
make verify-10
```

## Look around

- Repo → Settings → Branches → `main` rule.
- Repo → Settings → GitHub Apps (or your profile → Applications → Installed GitHub Apps): the App,
  with access to one repository.
- Open a trivial PR yourself: both checks run. `agent-scope-guard` says "not applicable" because
  you're not the agent.

**Next:** [11 · The agent](../11-agent/)
