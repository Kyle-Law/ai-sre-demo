# Incident SUP-8

- Ticket: https://kylelaw1121.atlassian.net/browse/SUP-8
- Recorded: 2026-10-18 18:01:22 UTC
- Diagnosed by: AI SRE agent (`claude-haiku-5-5`), confidence **high**

## Alerts
- `ContainerOOMKilled` shop/checkout since 2026-10-18T18:00:30Z

## Summary
shop/checkout is OOMKilled in a crash loop because commit 0ba1745 ("rightsize memory request/limit per FinOps report") cut the memory limit from 256Mi to 64Mi and the request from 128Mi to 48Mi. The container's steady-state working set is ~120 MB, so it is killed every time it starts.

## Root cause
Commit 0ba17453b506 (Kyle Law, 2026-10-18 17:58:53Z) lowered checkout's memory limit to 64Mi and request to 48Mi. The deployment deliberately runs podinfo with --stress-memory=96 (its comment says it simulates a ~96 MB in-memory product catalog cache), so the process needs ~120 MB working set. It exceeds the 64Mi limit within seconds of starting and the kernel OOM-kills it (exit 137). ArgoCD auto-synced this change at 17:59:03Z, and the new ReplicaSet crash-loops while the old pods are still running on the previous ReplicaSet. The limit was rightsized from an average-usage view, which ignored the working set the app holds at startup.</root_cause>
<parameter name="evidence">["kubectl get pods -n shop: checkout-5bfcd877df-7pbss is CrashLoopBackOff with 4 restarts; the older ReplicaSet pods (checkout-6f7df9c775-*) are still Running.", "kubectl describe pod checkout-5bfcd877df-7pbss: Last State Terminated, Reason OOMKilled, Exit Code 137; Command includes --stress-memory=96; Limits memory 64Mi; Requests memory 48Mi.", "commit_diff 0ba17453b506: deployment.yaml memory request 128Mi -> 48Mi, limit 256Mi -> 64Mi, message 'chore(checkout): rightsize memory request/limit per FinOps report'.", "Argo CD app 'shop' (path 06-demo-app/manifests) synced revision 0ba17453b506 at 2026-10-18T17:59:03Z, which matches the start of the crash loop.", "promql container_memory_working_set_bytes for the checkout containers: the running pods sit at ~120-122 MB (about 117-122 MB across the 3 series), well above the 64Mi (~67 MB) limit and consistent with the 96 MB stress allocation.", "deployment.yaml comment: '# Simulates the in-memory product catalog cache (~96 MB).' The memory allocation is intentional, so the fix belongs in the limits, not in the app."]

## How it was found
1. Listed pods in shop. checkout-5bfcd877df-7pbss (new ReplicaSet) is in CrashLoopBackOff with 4 restarts. The two older checkout-6f7df9c775 pods are still Running, so the regression is in the new rollout.
1. Pulled the Argo CD application list. App 'shop' maps to path 06-demo-app/manifests and last synced revision 0ba17453b506 at 17:59:03Z, which lines up with when the crash loop started.
1. kubectl describe on the crashing pod showed Last State OOMKilled (exit 137), a memory limit of 64Mi and a request of 48Mi, and the command --stress-memory=96.
1. recent_commits on the path and commit_diff of 0ba17453b506 showed the FinOps 'rightsize' change: memory request 128Mi->48Mi and limit 256Mi->64Mi.
1. Read deployment.yaml. The stress-memory=96 flag is intentional and documented as simulating a ~96 MB catalog cache. So the app legitimately needs ~120 MB, and the 64Mi limit (~67 MB) cannot hold it.
1. promql working-set data for the running checkout pods shows ~117-122 MB steady state, confirming the limit is too low and that the old 256Mi limit gives ample headroom.
1. Conclusion: revert the memory request/limit in deployment.yaml to 128Mi/256Mi (the pre-0ba1745 values). Leave all other settings as they were. Proposed a PR.

## Evidence


## Remediation (this PR)
- `06-demo-app/manifests/deployment.yaml`

Risk: Memory limit goes back to 256Mi, so the reserved memory per checkout pod rises by about 192Mi (x2 replicas plus surge). This is a cost increase that the FinOps change was trying to avoid. The app's usage (~120 MB) fits well inside the limit, so no OOM risk remains. The CPU request (50m) and the probe changes are untouched.

Rollback: Revert this PR. ArgoCD will re-sync, which restores the 48Mi/64Mi values and the OOM crash loop. Rightsizing should be done later against p99 working-set metrics, with the limit kept above the startup allocation.
