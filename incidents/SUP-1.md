# Incident SUP-1

- Ticket: https://kylelaw1121.atlassian.net/browse/SUP-1
- Recorded: 2026-10-17 16:25:02 UTC
- Diagnosed by: AI SRE agent (`claude-sonnet-5-5`), confidence **high**

## Alerts
- `ContainerOOMKilled` shop/checkout since 2026-10-17T16:21:30Z
- `DeploymentRolloutStuck` shop/checkout since 2026-10-17T16:23:30Z

## Summary
The new checkout pod is OOMKilled in a CrashLoopBackOff, so the rollout is stuck. Commit 10462172 cut the memory limit to 64Mi, but the app deliberately holds about 96 MB (--stress-memory=96).

## Root cause
Commit 10462172c065 ("chore(checkout): rightsize memory request/limit per FinOps report", Kyle Law) lowered the checkout memory request from 128Mi to 48Mi and the limit from 256Mi to 64Mi. The container is started with --stress-memory=96, which simulates a ~96 MB in-memory catalog cache. That allocation exceeds the 64Mi limit, so the container is OOMKilled (exit 137) within about a second of starting. The new ReplicaSet never becomes ready. The old pods are still serving because maxUnavailable=0, and the progress deadline then fires the DeploymentRolloutStuck alert. The FinOps report looked at average usage and missed the fixed cache allocation.

## Evidence
- kubectl get pods -n shop: the new pod checkout-5bfcd877df-6dr78 is in CrashLoopBackOff with 5 restarts. The two old pods from ReplicaSet 6f7df9c775 are still Running.
- kubectl describe pod: Last State Terminated, Reason OOMKilled, Exit Code 137. It ran for about 1s (00:23:04 to 00:23:05). Limits memory 64Mi, requests memory 48Mi. Command includes --stress-memory=96.
- commit_diff 10462172c065: memory request 128Mi -> 48Mi and limit 256Mi -> 64Mi in 06-demo-app/manifests/deployment.yaml.
- ArgoCD app 'shop' synced revision 10462172 at 16:20:07Z and is Degraded. The alerts started at 16:21:30Z and 16:23:30Z, shortly after the sync.

## Remediation (this PR)
- `06-demo-app/manifests/deployment.yaml`

Risk: Low. This only restores the previous known-good memory values, so each pod reserves about 80Mi more request and 192Mi more limit. This undoes the FinOps saving. Any future rightsizing must stay above the ~96 MB working set plus headroom.

Rollback: Revert the PR. That brings back the 48Mi/64Mi values, which will OOM again.
