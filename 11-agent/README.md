# 11 · The agent

**Goal:** run the AI SRE agent. It picks up `ai-triage` tickets, investigates with its read-only
eyes, proposes a fix as a PR, then follows that PR through review, merge, ArgoCD sync and recovery.

## Concepts

- **The loop** ([ai_sre_agent/workflow.py](ai_sre_agent/workflow.py)):
  1. poll Jira for open `ai-triage` tickets (created by step 08)
  2. **diagnose** with Claude using read-only tools: kubectl get/describe/logs/top/events, PromQL via
     Grafana, alert state, repo files, git history, commit diffs
  3. post the root cause, evidence, the offending commit and an investigation log to Jira
  4. open a PR (fix + `incidents/<KEY>.md`), mirror PR reviews to Jira, wait for the merge
  5. wait for ArgoCD to sync the merge commit, then verify the alert is gone and the replicas are
     healthy for `VERIFY_STABLE_SECONDS`
  6. post a timeline and MTTR, and close the ticket. If the fix didn't work: one more attempt, then
     `needs-human`. A PR a human closed is never retried.
- **Tool guard** ([ai_sre_agent/kube.py](ai_sre_agent/kube.py)): refuses non-read verbs, Secret
  resources and flags like `--as`, `--kubeconfig` or `--token` before kubectl even runs. RBAC
  (step 09) is the backstop.
- **Change validation** ([ai_sre_agent/diagnose.py](ai_sre_agent/diagnose.py)): proposed files must be
  under `AGENT_ALLOWED_PATHS` (`06-demo-app/manifests/`), parse as YAML, contain no
  Secret/RBAC/ServiceAccount kinds and stay small. CI (step 10) enforces the same scope.
- **Prompt-injection stance** ([ai_sre_agent/prompts.py](ai_sre_agent/prompts.py)): logs, events,
  commit messages and ticket text are treated as untrusted data, never as instructions.
- **Isolation on a laptop**: [run.sh](run.sh) installs the agent into `.venv`, **unsets your
  `KUBECONFIG`** so the agent only gets `agent.kubeconfig`, and keeps state and the audit log in
  `.agent/`.

## Configure

```bash
cp 11-agent/.env.example agent.env && chmod 600 agent.env && $EDITOR agent.env
#   ANTHROPIC_API_KEY
#   GRAFANA_TOKEN            <- 09-agent-access/create-grafana-token.sh
#   JIRA_*                   (same site/project as step 08)
#   GITHUB_APP_ID            <- step 10 output; GITHUB_APP_PRIVATE_KEY_PATH=github-app.pem
#   GITHUB_REPO, GITHUB_REVIEWERS=<your github user>
```

## Run

```bash
make verify-11                 # selftest: every connection + RBAC matrix, all PASS
DRY_RUN=true make step-11      # rehearse: investigates and prints Jira comments / PR, writes nothing
make step-11                   # the real loop (Ctrl-C stops after the current cycle)
```

## Look around

```bash
tail -f .agent/audit.jsonl | jq .            # every tool call, every external write
./11-agent/run.sh status                     # incidents in the local state DB, with timelines
./11-agent/run.sh diagnose <KEY>             # e.g. INC-1: investigate a real ticket, print only
make test                                    # offline tests: agent lifecycle against fakes
```

**Next:** [12 · Failure scenarios](../12-scenarios/)
