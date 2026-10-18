# 14 · Demo runbook (≈20 minutes)

The stage script for showing the whole system end to end. Steps 01–13 must be done.

## Screens to have open

1. **Grafana**: Alerting → Alert rules → folder *AI SRE Demo*
2. **Jira**: the INC board, filtered on `labels = ai-triage`
3. **GitHub**: the repo's Pull requests tab
4. **ArgoCD**: the `shop` application tree
5. **Terminal A**: `make step-11` (the agent's live log)
6. **Terminal B**: repo checkout for `13-scenarios/demo.py`

## T-30 min

```bash
make verify-14                                # preflight across every step, all OK
make verify-11                                # agent selftest, all PASS
python3 13-scenarios/demo.py status           # "Active scenario: none", no drift
```

Confirm the agent kubeconfig token hasn't expired (the expiry is in the file header).

## 1. Set the scene (3 min)

- One workload, `checkout`, deployed by ArgoCD from git. Everything is code: alert rules, RBAC, the app.
- Show the agent's identity in Terminal B, using the agent kubeconfig:
  ```bash
  KUBECONFIG=agent.kubeconfig ./09-agent-access/verify-rbac.sh
  ```
  Talking point: *"It can see everything it needs to diagnose, and nothing that lets it change the
  cluster. No Secrets, no exec. The final line is a real delete attempt the API server rejects."*
- Show branch protection: one approval, CODEOWNERS, required checks. The agent is a GitHub App
  installed on this one repo: it can open PRs, it can't approve or merge them.

## 2. Break production (1 min)

```bash
python3 13-scenarios/demo.py inject 01-oomkilled
```

Talking point: *"This is a FinOps 'rightsizing' commit. It looks reasonable and it was pushed to
main. Watch what happens."*

Show the commit in GitHub, then in ArgoCD as the new ReplicaSet appears.

## 3. Detection → ticket (≈2 min wait)

- Grafana: `ContainerOOMKilled` goes Pending, then Firing.
- Jira: a ticket appears, created by the alert bridge, with the alert payload and a Grafana link.
- Talking point while waiting: *"Old pods keep serving because the rolling update protects us. But
  the deploy is broken and nobody has been woken up yet."*

## 4. The agent investigates (≈1–2 min)

Terminal A shows each read-only call. Jira gets:
1. **Picked up**: the ticket moves to In Progress.
2. **Diagnosis**: root cause, the offending **commit sha and author**, evidence, an investigation
   log of every command it ran, and the proposed diff.
3. **PR opened**, with a link.

Talking point: *"It found the commit, not just the symptom. The investigation log is the same set of
commands an SRE would run, and anyone can audit it."*

## 5. Human gate (2 min)

Open the PR. Walk through the summary, root cause, evidence, risk, rollback and investigation log.
Point out `incidents/INC-x.md` (the incident record goes into git) and the green `agent-scope-guard`
check.

Optional power move: request changes or leave a review comment, and show that it's mirrored to Jira.

**Approve and merge.**

## 6. GitOps applies, agent verifies (≈2–3 min)

- Jira: *PR merged by \<you\>*, then *ArgoCD synced revision …*.
- ArgoCD: the new ReplicaSet rolls out; the OOMKilled pods disappear.
- Grafana: the alert resolves (the bridge comments *RESOLVED*).
- After the stability window, Jira gets **Incident verified resolved** with a timeline table and
  **MTTR**, and the ticket moves to Done.

Talking point: *"MTTR was minutes, and most of it was me reading the PR. That's the time we want to
keep. The toil of finding the commit, gathering evidence and writing the fix is gone."*

## 7. The agent knows its limits (optional, 3 min)

```bash
python3 13-scenarios/demo.py reset
python3 13-scenarios/demo.py inject 06-node-cordoned   # uses your admin kind-ai-sre context
```

The agent finds the node is cordoned, explains that this isn't fixable in git, labels the ticket
`needs-human` and lists next steps. **No PR.** Reset with `python3 13-scenarios/demo.py reset --uncordon`.

## 8. Close (2 min)

Show `make report` (every incident's phases, MTTR, automated vs human time; `ARGS=--detail` adds how
each was found), then recap the
trust boundary: **read-only eyes, git-only hands, human-gated merge, Argo applies, agent verifies.**

## Between runs

```bash
python3 13-scenarios/demo.py reset --uncordon
```

Close the old Jira ticket, and wait for the `shop` app to show Synced/Healthy.

## If something goes wrong on stage

| Symptom | Quick fix |
|---|---|
| No ticket after 3 min | Grafana → Alert rules: is it Firing? `kubectl -n ai-sre logs deploy/alert-bridge` |
| Ticket but agent silent | Check Terminal A. Usually an expired kubeconfig (`make step-09` re-mints it) or wrong `JIRA_PROJECT_KEY` |
| PR merged but nothing syncs | ArgoCD → shop → Refresh (polls every 30s) |
| Verification slow | Expected `VERIFY_STABLE_SECONDS` (90s). Lower to 45 for the stage |
| Total failure | Narrate with `./11-agent/run.sh diagnose INC-x` (prints the diagnosis and PR without writing) |

## Timing knobs

| Setting | Default | Stage value |
|---|---|---|
| Grafana rule `for:` | 1m | 30s (edit `07-alert-rules/manifests/alert-rules.yaml`, push) |
| `POLL_SECONDS` | 20 | 10 |
| `VERIFY_STABLE_SECONDS` | 90 | 45 |
| ArgoCD `timeout.reconciliation` | 30s | 30s |
