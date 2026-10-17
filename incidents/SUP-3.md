# Incident SUP-3

- Ticket: https://kylelaw1121.atlassian.net/browse/SUP-3
- Recorded: 2026-10-17 18:40:42 UTC
- Diagnosed by: AI SRE agent (`claude-haiku-5-5`), confidence **high**

## Alerts
- `DeploymentRolloutStuck` shop/checkout since 2026-10-17T18:40:00Z

## Summary
shop/checkout new ReplicaSet never becomes Ready because its readiness probe targets port 8080, which podinfo does not listen on (it serves on 9898). Commit 5974e5c7 ("standardise health probes on port 8080") introduced this, and the rollout hit ProgressDeadlineExceeded.

## Root cause
Commit 5974e5c77742 changed the checkout readinessProbe httpGet port from 9898 to 8080 in 06-demo-app/manifests/deployment.yaml. The container is started with --port=9898 and only listens there, so every readiness check gets 'connection refused'. The new pod (checkout-84bf9b5ff9-2qt6v) stays 0/1 Ready, the RollingUpdate (maxUnavailable 0) stalls, and progressDeadlineSeconds=120 is exceeded. The liveness probe still uses 9898, so the pod is not restarted; it just never becomes Ready.</root_cause>
<parameter name="evidence">["kubectl get pods -n shop: checkout-84bf9b5ff9-2qt6v 0/1 Running, 3m39s old; the two checkout-6f7df9c775 pods are the old, still-serving ReplicaSet.", "kubectl describe pod checkout-84bf9b5ff9-2qt6v: 'Readiness: http-get http://:8080/readyz', 'Command: ./podinfo --port=9898', Events: 'Readiness probe failed: Get \"http://10.244.0.220:8080/readyz\": dial tcp 10.244.0.220:8080: connect: connection refused' (x25).", "kubectl logs deploy/checkout (old pod): 'Starting HTTP Server. addr :9898', so the app listens only on 9898.", "commit_diff 5974e5c77742 (Kyle Law, 2026-10-17T18:35:56Z, 'refactor(checkout): standardise health probes on port 8080'): readinessProbe port 9898 -> 8080. This is the only change in that commit.", "ArgoCD Application 'shop' (path 06-demo-app/manifests): health Degraded, synced to 5974e5c7 at 18:36:46Z, which is right before the alert started at 18:40Z."]

## Evidence


## Remediation (this PR)
- `06-demo-app/manifests/deployment.yaml`

Risk: Low. The change reverts one probe port to the value the container actually listens on. No resource limits, images, or other settings change. The stuck new pod should become Ready and the rollout should complete. The probe was not validated against a running cluster from this agent.

Rollback: Revert the PR. That restores the 8080 readiness probe and the stuck rollout, so only do it if the change itself causes a problem.
