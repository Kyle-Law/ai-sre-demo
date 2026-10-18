# Incident SUP-5

- Ticket: https://kylelaw1121.atlassian.net/browse/SUP-5
- Recorded: 2026-10-18 03:27:36 UTC
- Diagnosed by: AI SRE agent (`claude-haiku-5-5`), confidence **high**

## Alerts
- `PodUnschedulable` shop/checkout since 2026-10-18T03:26:30Z

## Summary
The shop/checkout rollout is stuck because commit f8741a7 ("perf(checkout): raise CPU request ahead of peak traffic") changed the container CPU request from 50m to "50" (50 whole cores). The single node cannot allocate that, so the new ReplicaSet pod is Pending with "Insufficient cpu" and the rollout hit ProgressDeadlineExceeded.

## Root cause
A unit error in the CPU request: "50" is read as 50 cores, not 50 millicores. The scheduler cannot place the pod on the single ai-sre-control-plane node, so the rolling update (maxSurge 1, maxUnavailable 0) is blocked. The 2 old pods remain Running, but the new revision never comes up.</root_cause>
<parameter name="evidence">["kubectl get pods -n shop: checkout-74d95868bb-rlzq6 Pending for 2m15s; the other two checkout pods (6f7df9c775) are Running on the single node.", "Event: FailedScheduling - '0/1 nodes are available: 1 Insufficient cpu. preemption: 0/1 nodes are available: 1 Preemption is not helpful for scheduling.'", "kubectl get deploy checkout -n shop: Progressing=False, reason ProgressDeadlineExceeded, 'ReplicaSet checkout-74d95868bb has timed out progressing'; pod spec shows requests cpu: \"50\".", "Commit f8741a70085d6d393a079de5126591b649698e3c (Kyle Law, 2026-10-18T03:24:31Z) diff: '-  cpu: 50m' '+  cpu: \"50\"' in 06-demo-app/manifests/deployment.yaml. ArgoCD synced this revision at 03:24:54Z, shortly before the alert at 03:26:30Z.", "ArgoCD app 'shop' (path 06-demo-app/manifests) is Degraded at revision f8741a7."]

## Evidence


## Remediation (this PR)
- `06-demo-app/manifests/deployment.yaml`

Risk: Low. Lowers the CPU request on the checkout Deployment back to its previous value (50m), so the new pod can schedule and the rollout can finish. The "peak traffic" intent is not addressed; if a larger request is wanted, set an intentional value (e.g. 500m) after checking node allocatable CPU.

Rollback: Revert this PR. Note that reverting it re-applies the bad value (cpu "50") and blocks scheduling again, so only roll back if this fix itself causes a problem.</rollback_plan>
<parameter name="verification_plan">After merge and ArgoCD sync: (1) kubectl get pods -n shop shows all checkout pods Running and Ready; (2) kubectl get deploy checkout -n shop shows Progressing=True and availableReplicas=2; (3) the 'shop' ArgoCD app is Healthy and Synced; (4) the PodUnschedulable alert resolves.
