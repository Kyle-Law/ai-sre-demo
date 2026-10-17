# Incident SUP-2

- Ticket: https://kylelaw1121.atlassian.net/browse/SUP-2
- Recorded: 2026-10-17 17:08:42 UTC
- Diagnosed by: AI SRE agent (`claude-sonnet-5-5`), confidence **high**

## Alerts
- `ContainerImagePullFailing` shop/checkout since 2026-10-17T17:08:00Z

## Summary
The checkout rollout is stuck because commit 1b7681aa changed the image to ghcr.io/stefanprodan/podinfo:6.15.0-hotfix1, a tag that doesn't exist in the registry. The new pod is in ImagePullBackOff. The two old pods are still serving.

## Root cause
Commit 1b7681aaa6a1 ("fix(checkout): roll out 6.15.0-hotfix1 for cart rounding bug", Kyle Law) pinned the checkout image to a tag that does not exist on ghcr.io. kubelet gets "not found" on every pull. maxUnavailable=0 keeps the two old 6.15.0 pods serving, so there is no outage yet, but the rollout cannot progress.

## Evidence
- kubectl get pods -n shop: checkout-5bcf9c47c5-tdc4t is in ImagePullBackOff. The two old pods from ReplicaSet 6f7df9c775 are Running 1/1.
- Pod events: Failed to pull image "ghcr.io/stefanprodan/podinfo:6.15.0-hotfix1": rpc error: code = NotFound ... ghcr.io/stefanprodan/podinfo:6.15.0-hotfix1: not found
- commit_diff 1b7681aaa6a1 changes only the image line in 06-demo-app/manifests/deployment.yaml, from podinfo:6.15.0 to podinfo:6.15.0-hotfix1.
- ArgoCD app 'shop' synced revision 1b7681aa at 17:06:43Z and is Progressing. The alert started at 17:08Z.
- Image 6.15.0 was already running healthy on the old pods before this commit.

## Remediation (this PR)
- `06-demo-app/manifests/deployment.yaml`

Risk: Low. This restores the image that is already running on the two healthy pods. The cart rounding hotfix is not deployed until a valid image tag is published.

Rollback: Revert this PR. Doing so would put the nonexistent hotfix1 tag back, so only do it once a real image exists.
