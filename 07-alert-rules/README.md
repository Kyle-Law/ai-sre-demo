# 07 · Alert rules

**Goal:** five Grafana alert rules, defined as code in git, that detect each way the demo app can
break. After this step alerts **fire in Grafana**, but they don't go anywhere yet (step 08).

## Concepts

- **Alerting as code**: [manifests/alert-rules.yaml](manifests/alert-rules.yaml) is a Grafana
  provisioning file. Kustomize wraps it in a ConfigMap labelled `grafana_alert=1`, and Grafana's
  **sidecar** container watches for that label and loads it. No clicking in the UI; the rules are
  read-only there.
- **The rules** are built on kube-state-metrics (step 05):

  | Rule | Fires when | Scenario (step 12) |
  |---|---|---|
  | `ContainerOOMKilled` | last termination reason is OOMKilled | 01 |
  | `ContainerImagePullFailing` | waiting in ErrImagePull / ImagePullBackOff | 02 |
  | `DeploymentRolloutStuck` | Deployment `Progressing=False` | 03 |
  | `ContainerConfigError` | CreateContainerConfigError | 04 |
  | `PodUnschedulable` | pod can't be scheduled | 05, 06 |

- **`workload` label**: `label_replace()` turns pod and container names into one `workload` label,
  so the bridge (step 08) can put several alerts for the same app into a single Jira ticket.
- **`ai_triage=true`**: every rule carries it. It's how a ticket gets routed to the AI agent.

## Run

```bash
make step-07
make verify-07      # rules loaded, every rule healthy, current state listed
```

## Look around

- Grafana → Alerting → Alert rules → folder **AI SRE Demo**. Open a rule to see its query and the
  `for:` pending period.
- Grafana → Explore: paste a rule's query (e.g. the `kube_pod_container_status_waiting_reason`
  one) to see what it evaluates to while everything is healthy (empty).
- Why not break the app with `kubectl edit`? ArgoCD's self-heal reverts manual changes within ~30s.
  To make an alert fire now, run `python3 12-scenarios/demo.py inject 02-bad-image-tag` (it pushes
  a bad commit) and `reset` afterwards.

**Next:** [08 · Jira integration](../08-jira-integration/)
