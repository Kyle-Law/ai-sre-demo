# Failure scenarios

`demo.py` breaks the `checkout` service the way real incidents usually start: a plausible commit
pushed to `main`. ArgoCD rolls it out, Grafana alerts, the bridge opens a Jira ticket, and the agent
has to find the cause and propose the fix.

```bash
python3 scenarios/demo.py list
python3 scenarios/demo.py baseline              # once, on known-good main
python3 scenarios/demo.py inject <id>           # --no-push / --dry-run to rehearse
python3 scenarios/demo.py reset --uncordon
```

Because of `maxUnavailable: 0`, the old pods keep serving during scenarios 01–05. The *rollout* is
broken, not the service. That's realistic, and it keeps the demo calm. Scenario 06 takes one replica
down.

---

## 01-oomkilled: memory limit "rightsized"

- **Commit:** `chore(checkout): rightsize memory limit per FinOps report`
- **Change:** `limits.memory: 256Mi → 64Mi`. The app keeps a ~96 MB catalog cache in memory
  (`--stress-memory=96`).
- **Alert:** `ContainerOOMKilled` (~2 min)
- **What the agent should find:** new pods `OOMKilled`/CrashLoopBackOff. `describe` shows
  `Last State: Terminated, Reason: OOMKilled`; `recent_commits` shows the FinOps commit; the memory
  working set (~110 MB) exceeds 64Mi.
- **Expected PR:** restore `memory: 256Mi`.
- **Talking point:** the cost optimisation wasn't wrong in spirit; it lacked the working-set data
  the agent pulled in seconds.

## 02-bad-image-tag: hotfix tag that doesn't exist

- **Commit:** `fix(checkout): roll out 6.15.0-hotfix1 for cart rounding bug`
- **Alert:** `ContainerImagePullFailing` (~2 min). After 120s, `DeploymentRolloutStuck` also fires
  and is **correlated onto the same ticket**.
- **What the agent should find:** `ErrImagePull … manifest unknown` in events.
- **Expected PR:** image back to `6.15.0`, with a note that the hotfix tag needs publishing first.

## 03-readiness-probe: probe on the wrong port

- **Commit:** `refactor(checkout): standardise health probes on port 8080`
- **Alert:** `DeploymentRolloutStuck` (~3–4 min: 120s progress deadline + 1m)
- **What the agent should find:** new pods Running but 0/1 Ready; events `Readiness probe failed:
  … connect: connection refused` on :8080; the container listens on 9898.
- **Expected PR:** readiness port back to `9898`.

## 04-configmap-key: key renamed, reference not updated

- **Commit:** `refactor(checkout): rename ui.message config key to ui.banner` (also bumps the
  config-revision annotation, which rolls the pods)
- **Alert:** `ContainerConfigError` (~2 min)
- **What the agent should find:** `CreateContainerConfigError: couldn't find key ui.message in
  ConfigMap shop/checkout-config`.
- **Expected PR:** rename the key back, or point `configMapKeyRef` at `ui.banner`. Either is valid,
  and the reviewer can discuss which.

## 05-cpu-request-typo: 50 cores instead of 500m

- **Commit:** `perf(checkout): raise CPU request ahead of peak traffic`
- **Change:** `requests.cpu: 50m → "50"`
- **Alert:** `PodUnschedulable` (~2 min)
- **What the agent should find:** `0/1 nodes are available: 1 Insufficient cpu`; node allocatable
  is a few cores.
- **Expected PR:** `500m` (the evident intent) or back to `50m`, with the reasoning stated.

## 06-node-cordoned: not fixable in git

- **Action (outside git):** `kubectl cordon` on the node, then one checkout pod is deleted
- **Alert:** `PodUnschedulable` (~2 min)
- **What the agent should find:** `node(s) were unschedulable`; node `spec.unschedulable: true`;
  no recent commit explains it.
- **Expected outcome:** **no PR**. The agent escalates, labels the ticket `needs-human`, and
  recommends `kubectl uncordon` after checking why the node was cordoned.
- **Talking point:** a trustworthy agent knows what it can't, or shouldn't, fix.

---

## Adding your own

Add an entry to `SCENARIOS` in `demo.py`: either `edits` (exact `find` → `replace` on files under
`apps/`, each matching exactly once) or `cluster_actions` (shell one-liners). Add a matching Grafana
rule in `platform/monitoring-config/alert-rules.yaml` if no existing rule covers it.
`tests/test_repo.py` checks that every scenario has an alert rule and applies cleanly.
