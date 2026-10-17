# Incident SUP-4

- Ticket: https://kylelaw1121.atlassian.net/browse/SUP-4
- Recorded: 2026-10-17 19:07:12 UTC
- Diagnosed by: AI SRE agent (`claude-sonnet-5-5`), confidence **high**

## Alerts
- `ContainerConfigError` shop/checkout since 2026-10-17T19:06:30Z

## Summary
The new checkout pod can't start because commit 006ae7e renamed the ConfigMap key ui.message to ui.banner. The Deployment still reads ui.message through a non-optional configMapKeyRef.

## Root cause
Commit 006ae7e73ce0 (Kyle Law, "refactor(checkout): rename ui.message config key to ui.banner") changed configmap.yaml to define ui.banner instead of ui.message. It also bumped the pod-template annotation config-revision to 2, which triggered a rollout. deployment.yaml still sets PODINFO_UI_MESSAGE from key 'ui.message' of checkout-config (Optional: false), so the new pod fails with CreateContainerConfigError. The two old pods are still running, so the outage is partial and the rollout is stuck.

## Evidence
- Pod checkout-55fd8c6cd6-gtr9g is in CreateContainerConfigError. The event reads: Error: couldn't find key ui.message in ConfigMap shop/checkout-config
- The pod's environment shows PODINFO_UI_MESSAGE sourced from key 'ui.message' of config map 'checkout-config', Optional: false
- Two old pods from ReplicaSet checkout-6f7df9c775 are still Running, so the rollout is stuck.
- commit_diff 006ae7e73ce0 shows configmap.yaml changed from ui.message to ui.banner, with no matching change to the deployment's key reference.
- The ArgoCD 'shop' app synced 006ae7e at 19:05:11Z, and the alert started at 19:06:30Z.

## Remediation (this PR)
- `06-demo-app/manifests/configmap.yaml`

Risk: Low. This reverts one ConfigMap key to the value the Deployment already references. The config-revision annotation stays at 2, so no extra rollout is triggered. If anything else has started reading ui.banner, it would need updating, but nothing in the repo does.

Rollback: Revert the PR. A later key rename should update the deployment's configMapKeyRef in the same commit.
