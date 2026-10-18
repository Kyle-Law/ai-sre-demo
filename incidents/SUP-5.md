# Incident SUP-5

- Ticket: https://kylelaw1121.atlassian.net/browse/SUP-5
- Recorded: 2026-10-18 03:27:36 UTC
- Diagnosed by: AI SRE agent (`claude-sonnet-5-5`), confidence **high**

## Alerts
- `PodUnschedulable` shop/checkout since 2026-10-18T03:26:30Z

## Summary
The checkout CPU request was changed from 50m to "50" (50 full cores), so the new ReplicaSet's pod can't fit on the 12-CPU node and stays Pending. The change looks like a unit typo.

## Root cause
Commit f8741a70085d ("perf(checkout): raise CPU request ahead of peak traffic", Kyle Law) changed resources.requests.cpu from 50m to "50". That is 50 cores, not 50 millicores. The only node has 12 CPUs allocatable, so the scheduler reports "Insufficient cpu". The rolling update is stuck: the new pod checkout-74d95868bb-rlzq6 is Pending, and the two old pods keep serving because maxUnavailable is 0. The fix restores the previous 50m request. If a real increase is wanted, a human should choose a value in millicores, for example 250m or 500m, based on load data.

## Evidence
- Pod checkout-74d95868bb-rlzq6 is Pending. Event: FailedScheduling 0/1 nodes are available: 1 Insufficient cpu.
- kubectl describe pod shows Requests: cpu: 50 (50 cores). The old pods request 50m.
- Node ai-sre-control-plane has 12 CPU allocatable and 1360m already requested. It is Ready, untainted and not cordoned.
- commit_diff f8741a70085d: deployment.yaml changed `cpu: 50m` to `cpu: "50"`.
- ArgoCD app 'shop' is Degraded at revision f8741a70085d, which was synced at 03:24:54Z. The alert fired at 03:26:30Z.

## Remediation (this PR)
- `06-demo-app/manifests/deployment.yaml`

Risk: Low. This returns the CPU request to the value the two running pods already use. It does not deliver the CPU increase the original commit intended. That increase should be re-proposed with a sane millicore value.

Rollback: Revert the PR. Do not do this unless the CPU request is also corrected, because the 50-core request will make the pod unschedulable again.
