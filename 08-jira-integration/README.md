# 08 · Jira integration

**Goal:** firing alerts become Jira tickets. Several alerts for the same workload go into one
ticket, and the ticket gets the `ai-triage` label the agent (step 11) watches for.

## Concepts

- **Contact point + notification policy** ([manifests/contact-points.yaml](manifests/contact-points.yaml),
  [manifests/notification-policies.yaml](manifests/notification-policies.yaml)): Grafana sends
  alerts as webhooks to the in-cluster bridge, grouped by `alertname, namespace, workload`. Like the
  step 07 rules, they're provisioned through the sidecar label `grafana_alert=1`.
- **The alert bridge** ([manifests/bridge.py](manifests/bridge.py)): a small stdlib-only Python
  service that runs on the stock `python` image, with the code mounted from a ConfigMap (no image
  build):
  - firing alert, no open ticket for that workload → **create** a ticket labelled `ai-triage`
  - firing alert, open ticket for the same workload → **comment** on it ("correlated alert")
  - resolved alert → comment `RESOLVED`
- **Least privilege for the bridge**: no ServiceAccount token mounted, non-root, read-only root
  filesystem. Jira credentials come from a Secret that `run.sh` creates from `demo.env`.
- **NetworkPolicy** ([manifests/networkpolicy.yaml](manifests/networkpolicy.yaml)): only pods in the
  `monitoring` namespace can reach the bridge. Cilium (step 02) enforces it; `verify.sh` proves it
  from both sides.
- **One Application, two namespaces**: the bridge lives in `ai-sre`, while the Grafana ConfigMaps
  must live in `monitoring` (the sidecar only watches there). Each resource sets its own namespace in
  the kustomization.

## Run

Fill in `JIRA_*` in `demo.env` first (Jira project key `INC`; an API token from
<https://id.atlassian.com/manage-profile/security/api-tokens>).

```bash
make step-08
make verify-08                                   # bridge, Grafana routing, NetworkPolicy both ways
./08-jira-integration/verify.sh --send-test-alert   # creates + resolves one real ticket
```

## Look around

```bash
kubectl -n ai-sre logs deploy/alert-bridge -f            # JSON log line per alert
kubectl -n kube-system port-forward svc/hubble-ui 12000:80
#   Hubble UI -> namespace ai-sre: green flows from grafana, red (dropped) ones from the default-ns test pod
```

Grafana → Alerting → Contact points → `jira-bridge` → **Test** sends a sample alert. The bridge
ignores it because it has no `ai_triage` label; you'll see `skipped` in its log.

**Next:** [09 · Agent access](../09-agent-access/)
