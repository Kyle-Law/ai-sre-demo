# Incident SUP-7

- Ticket: https://kylelaw1121.atlassian.net/browse/SUP-7
- Recorded: 2026-10-18 15:20:03 UTC
- Diagnosed by: AI SRE agent (`claude-haiku-5-5`), confidence **high**

## Alerts
- `DeploymentRolloutStuck` shop/checkout since 2026-10-18T15:19:00Z

## Summary
shop/checkout new ReplicaSet never becomes Ready because its readiness probe was changed to port 8080 in commit 8f74ec2, while podinfo listens on 9898. Reverting that one line restores the rollout.

## Root cause
Commit 8f74ec269128 (Kyle Law, "refactor(checkout): standardise health probes on port 8080") changed the checkout Deployment's readinessProbe httpGet port from 9898 to 8080. The container only serves HTTP on 9898 (command --port=9898, containerPort 9898), so the readiness probe gets "connection refused" on every attempt. The new ReplicaSet's pod stays 0/1, the rollout hits progressDeadlineSeconds=120, and Progressing becomes False (ProgressDeadlineExceeded). The same bad change (5974e5c) was previously introduced and reverted by SUP-3 (7eb4f66), so it was reintroduced.</root_cause>
<parameter name="evidence">["kubectl get pods -n shop: checkout-84bf9b5ff9-h7qb4 is 0/1 Running, age ~4m, while the two older checkout-6f7df9c775 pods are 1/1 Running.", "Events: 'Readiness probe failed: Get \"http://10.244.0.233:8080/readyz\": dial tcp 10.244.0.233:8080: connect: connection refused' (x25).", "kubectl describe pod: readinessProbe http-get :8080/readyz; container command --port=9898 and containerPort 9898; liveness probe still on 9898.", "commit_diff 8f74ec269128: readinessProbe port 9898 -> 8080 in 06-demo-app/manifests/deployment.yaml.", "recent_commits: 5974e5c77742 (Kyle Law, same 'standardise health probes on port 8080' message) was reverted by 7eb4f66596cc ([SUP-3] Restore checkout readiness probe to port 9898).", "ArgoCD app 'shop' (path 06-demo-app/manifests) synced revision 8f74ec2 at 2026-10-18T15:15:35Z, which matches the start of the failure."]

## How it was found
1. [
1. "
1. C
1. h
1. e
1. c
1. k
1. e
1. d
1.  
1. t
1. h
1. e
1.  
1. s
1. h
1. o
1. p
1.  
1. p
1. o
1. d
1. s
1.  
1. a
1. n
1. d
1.  
1. e
1. v
1. e
1. n
1. t
1. s
1. .
1.  
1. O
1. n
1. e
1.  
1. n
1. e
1. w
1.  
1. R
1. e
1. p
1. l
1. i
1. c
1. a
1. S
1. e
1. t
1.  
1. p
1. o
1. d
1.  
1. (
1. c
1. h
1. e
1. c
1. k
1. o
1. u
1. t
1. -
1. 8
1. 4
1. b
1. f
1. 9
1. b
1. 5
1. f
1. f
1. 9
1. -
1. h
1. 7
1. q
1. b
1. 4
1. )
1.  
1. i
1. s
1.  
1. 0
1. /
1. 1
1.  
1. w
1. i
1. t
1. h
1.  
1. r
1. e
1. p
1. e
1. a
1. t
1. e
1. d
1.  
1. r
1. e
1. a
1. d
1. i
1. n
1. e
1. s
1. s
1.  
1. '
1. c
1. o
1. n
1. n
1. e
1. c
1. t
1. i
1. o
1. n
1.  
1. r
1. e
1. f
1. u
1. s
1. e
1. d
1. '
1.  
1. o
1. n
1.  
1. 1
1. 0
1. .
1. 2
1. 4
1. 4
1. .
1. 0
1. .
1. 2
1. 3
1. 3
1. :
1. 8
1. 0
1. 8
1. 0
1. .
1.  
1. T
1. h
1. e
1.  
1. o
1. l
1. d
1. e
1. r
1.  
1. p
1. o
1. d
1. s
1.  
1. a
1. r
1. e
1.  
1. h
1. e
1. a
1. l
1. t
1. h
1. y
1. .
1. "
1. ,
1.  
1. "
1. F
1. o
1. u
1. n
1. d
1.  
1. t
1. h
1. e
1.  
1. A
1. r
1. g
1. o
1. C
1. D
1.  
1. a
1. p
1. p
1.  
1. t
1. h
1. a
1. t
1.  
1. d
1. e
1. p
1. l
1. o
1. y
1. s
1.  
1. s
1. h
1. o
1. p
1.  
1. (
1. a
1. p
1. p
1.  
1. '
1. s
1. h
1. o
1. p
1. '
1. ,
1.  
1. p
1. a
1. t
1. h
1.  
1. 0
1. 6
1. -
1. d
1. e
1. m
1. o
1. -
1. a
1. p
1. p
1. /
1. m
1. a
1. n
1. i
1. f
1. e
1. s
1. t
1. s
1. )
1. .
1.  
1. I
1. t
1. s
1.  
1. l
1. a
1. s
1. t
1.  
1. s
1. y
1. n
1. c
1.  
1. w
1. a
1. s
1.  
1. r
1. e
1. v
1. i
1. s
1. i
1. o
1. n
1.  
1. 8
1. f
1. 7
1. 4
1. e
1. c
1. 2
1.  
1. a
1. t
1.  
1. 1
1. 5
1. :
1. 1
1. 5
1. :
1. 3
1. 5
1. Z
1. ,
1.  
1. j
1. u
1. s
1. t
1.  
1. b
1. e
1. f
1. o
1. r
1. e
1.  
1. t
1. h
1. e
1.  
1. f
1. a
1. i
1. l
1. u
1. r
1. e
1.  
1. s
1. t
1. a
1. r
1. t
1. e
1. d
1. .
1. "
1. ,
1.  
1. "
1. D
1. e
1. s
1. c
1. r
1. i
1. b
1. e
1. d
1.  
1. t
1. h
1. e
1.  
1. p
1. o
1. d
1. :
1.  
1. r
1. e
1. a
1. d
1. i
1. n
1. e
1. s
1. s
1. P
1. r
1. o
1. b
1. e
1.  
1. t
1. a
1. r
1. g
1. e
1. t
1. s
1.  
1. p
1. o
1. r
1. t
1.  
1. 8
1. 0
1. 8
1. 0
1. ,
1.  
1. b
1. u
1. t
1.  
1. t
1. h
1. e
1.  
1. c
1. o
1. n
1. t
1. a
1. i
1. n
1. e
1. r
1.  
1. r
1. u
1. n
1. s
1.  
1. p
1. o
1. d
1. i
1. n
1. f
1. o
1.  
1. w
1. i
1. t
1. h
1.  
1. -
1. -
1. p
1. o
1. r
1. t
1. =
1. 9
1. 8
1. 9
1. 8
1.  
1. a
1. n
1. d
1.  
1. e
1. x
1. p
1. o
1. s
1. e
1. s
1.  
1. o
1. n
1. l
1. y
1.  
1. 9
1. 8
1. 9
1. 8
1.  
1. (
1. p
1. l
1. u
1. s
1.  
1. m
1. e
1. t
1. r
1. i
1. c
1. s
1.  
1. 9
1. 7
1. 9
1. 7
1. )
1. .
1. "
1. ,
1.  
1. "
1. P
1. u
1. l
1. l
1. e
1. d
1.  
1. r
1. e
1. c
1. e
1. n
1. t
1.  
1. c
1. o
1. m
1. m
1. i
1. t
1. s
1.  
1. f
1. o
1. r
1.  
1. t
1. h
1. e
1.  
1. p
1. a
1. t
1. h
1. .
1.  
1. 8
1. f
1. 7
1. 4
1. e
1. c
1. 2
1.  
1. (
1. K
1. y
1. l
1. e
1.  
1. L
1. a
1. w
1. )
1.  
1. i
1. s
1.  
1. t
1. h
1. e
1.  
1. n
1. e
1. w
1. e
1. s
1. t
1. ,
1.  
1. a
1. n
1. d
1.  
1. i
1. t
1. s
1.  
1. d
1. i
1. f
1. f
1.  
1. c
1. h
1. a
1. n
1. g
1. e
1. s
1.  
1. o
1. n
1. l
1. y
1.  
1. t
1. h
1. e
1.  
1. r
1. e
1. a
1. d
1. i
1. n
1. e
1. s
1. s
1. P
1. r
1. o
1. b
1. e
1.  
1. p
1. o
1. r
1. t
1.  
1. 9
1. 8
1. 9
1. 8
1.  
1. -
1. >
1.  
1. 8
1. 0
1. 8
1. 0
1. .
1. "
1. ,
1.  
1. "
1. F
1. o
1. u
1. n
1. d
1.  
1. t
1. h
1. a
1. t
1.  
1. t
1. h
1. e
1.  
1. i
1. d
1. e
1. n
1. t
1. i
1. c
1. a
1. l
1.  
1. c
1. h
1. a
1. n
1. g
1. e
1.  
1. (
1. 5
1. 9
1. 7
1. 4
1. e
1. 5
1. c
1. )
1.  
1. w
1. a
1. s
1.  
1. m
1. a
1. d
1. e
1.  
1. e
1. a
1. r
1. l
1. i
1. e
1. r
1.  
1. a
1. n
1. d
1.  
1. r
1. e
1. v
1. e
1. r
1. t
1. e
1. d
1.  
1. b
1. y
1.  
1. S
1. U
1. P
1. -
1. 3
1.  
1. (
1. 7
1. e
1. b
1. 4
1. f
1. 6
1. 6
1. )
1. ,
1.  
1. w
1. h
1. i
1. c
1. h
1.  
1. r
1. e
1. s
1. t
1. o
1. r
1. e
1. d
1.  
1. p
1. o
1. r
1. t
1.  
1. 9
1. 8
1. 9
1. 8
1. .
1.  
1. T
1. h
1. e
1.  
1. s
1. a
1. m
1. e
1.  
1. r
1. e
1. g
1. r
1. e
1. s
1. s
1. i
1. o
1. n
1.  
1. c
1. a
1. m
1. e
1.  
1. b
1. a
1. c
1. k
1.  
1. i
1. n
1.  
1. 8
1. f
1. 7
1. 4
1. e
1. c
1. 2
1. .
1. "
1. ,
1.  
1. "
1. C
1. o
1. n
1. c
1. l
1. u
1. s
1. i
1. o
1. n
1. :
1.  
1. t
1. h
1. e
1.  
1. r
1. e
1. a
1. d
1. i
1. n
1. e
1. s
1. s
1.  
1. p
1. r
1. o
1. b
1. e
1.  
1. p
1. o
1. r
1. t
1.  
1. i
1. s
1.  
1. w
1. r
1. o
1. n
1. g
1. ,
1.  
1. s
1. o
1.  
1. t
1. h
1. e
1.  
1. n
1. e
1. w
1.  
1. p
1. o
1. d
1.  
1. c
1. a
1. n
1.  
1. n
1. e
1. v
1. e
1. r
1.  
1. b
1. e
1. c
1. o
1. m
1. e
1.  
1. R
1. e
1. a
1. d
1. y
1.  
1. a
1. n
1. d
1.  
1. t
1. h
1. e
1.  
1. r
1. o
1. l
1. l
1. o
1. u
1. t
1.  
1. s
1. t
1. a
1. l
1. l
1. s
1. .
1.  
1. R
1. e
1. v
1. e
1. r
1. t
1. i
1. n
1. g
1.  
1. t
1. h
1. a
1. t
1.  
1. s
1. i
1. n
1. g
1. l
1. e
1.  
1. l
1. i
1. n
1. e
1.  
1. t
1. o
1.  
1. 9
1. 8
1. 9
1. 8
1.  
1. i
1. s
1.  
1. t
1. h
1. e
1.  
1. m
1. i
1. n
1. i
1. m
1. a
1. l
1.  
1. f
1. i
1. x
1. .
1. "
1. ]
1. <
1. /
1. r
1. e
1. a
1. s
1. o
1. n
1. i
1. n
1. g
1. _
1. s
1. t
1. e
1. p
1. s
1. >
1. 

1. <
1. p
1. a
1. r
1. a
1. m
1. e
1. t
1. e
1. r
1.  
1. n
1. a
1. m
1. e
1. =
1. "
1. r
1. i
1. s
1. k
1. "
1. >
1. L
1. o
1. w
1. .
1.  
1. T
1. h
1. i
1. s
1.  
1. c
1. h
1. a
1. n
1. g
1. e
1. s
1.  
1. o
1. n
1. e
1.  
1. r
1. e
1. a
1. d
1. i
1. n
1. e
1. s
1. s
1.  
1. p
1. r
1. o
1. b
1. e
1.  
1. p
1. o
1. r
1. t
1.  
1. b
1. a
1. c
1. k
1.  
1. t
1. o
1.  
1. t
1. h
1. e
1.  
1. v
1. a
1. l
1. u
1. e
1.  
1. t
1. h
1. a
1. t
1.  
1. w
1. o
1. r
1. k
1. e
1. d
1.  
1. b
1. e
1. f
1. o
1. r
1. e
1.  
1. 8
1. f
1. 7
1. 4
1. e
1. c
1. 2
1.  
1. a
1. n
1. d
1.  
1. m
1. a
1. t
1. c
1. h
1. e
1. s
1.  
1. t
1. h
1. e
1.  
1. c
1. o
1. n
1. t
1. a
1. i
1. n
1. e
1. r
1. '
1. s
1.  
1. l
1. i
1. s
1. t
1. e
1. n
1. i
1. n
1. g
1.  
1. p
1. o
1. r
1. t
1. .
1.  
1. T
1. h
1. e
1.  
1. l
1. i
1. v
1. e
1. n
1. e
1. s
1. s
1.  
1. p
1. r
1. o
1. b
1. e
1.  
1. i
1. s
1.  
1. a
1. l
1. r
1. e
1. a
1. d
1. y
1.  
1. o
1. n
1.  
1. 9
1. 8
1. 9
1. 8
1. .
1.  
1. R
1. e
1. a
1. d
1. i
1. n
1. e
1. s
1. s
1.  
1. w
1. i
1. l
1. l
1.  
1. s
1. t
1. a
1. r
1. t
1.  
1. p
1. a
1. s
1. s
1. i
1. n
1. g
1. ,
1.  
1. t
1. h
1. e
1.  
1. r
1. o
1. l
1. l
1. o
1. u
1. t
1.  
1. w
1. i
1. l
1. l
1.  
1. c
1. o
1. m
1. p
1. l
1. e
1. t
1. e
1. ,
1.  
1. a
1. n
1. d
1.  
1. t
1. h
1. e
1.  
1. o
1. l
1. d
1.  
1. R
1. e
1. p
1. l
1. i
1. c
1. a
1. S
1. e
1. t
1.  
1. w
1. i
1. l
1. l
1.  
1. s
1. c
1. a
1. l
1. e
1.  
1. d
1. o
1. w
1. n
1. .
1.  
1. T
1. h
1. e
1.  
1. o
1. n
1. l
1. y
1.  
1. s
1. i
1. d
1. e
1.  
1. e
1. f
1. f
1. e
1. c
1. t
1.  
1. i
1. s
1.  
1. t
1. h
1. a
1. t
1.  
1. t
1. h
1. e
1.  
1. t
1. e
1. a
1. m
1. '
1. s
1.  
1. i
1. n
1. t
1. e
1. n
1. d
1. e
1. d
1.  
1. p
1. o
1. r
1. t
1.  
1. s
1. t
1. a
1. n
1. d
1. a
1. r
1. d
1. i
1. s
1. a
1. t
1. i
1. o
1. n
1.  
1. i
1. s
1.  
1. u
1. n
1. d
1. o
1. n
1. e
1. ,
1.  
1. s
1. o
1.  
1. i
1. t
1.  
1. s
1. h
1. o
1. u
1. l
1. d
1.  
1. b
1. e
1.  
1. r
1. e
1. d
1. o
1. n
1. e
1.  
1. c
1. o
1. r
1. r
1. e
1. c
1. t
1. l
1. y
1.  
1. i
1. f
1.  
1. i
1. t
1.  
1. i
1. s
1.  
1. s
1. t
1. i
1. l
1. l
1.  
1. w
1. a
1. n
1. t
1. e
1. d
1.  
1. (
1. t
1. h
1. e
1.  
1. c
1. o
1. n
1. t
1. a
1. i
1. n
1. e
1. r
1.  
1. w
1. o
1. u
1. l
1. d
1.  
1. n
1. e
1. e
1. d
1.  
1. t
1. o
1.  
1. l
1. i
1. s
1. t
1. e
1. n
1.  
1. o
1. n
1.  
1. 8
1. 0
1. 8
1. 0
1. )
1. .

## Evidence


## Remediation (this PR)
- `06-demo-app/manifests/deployment.yaml`

Risk: -

Rollback: Revert the PR. Re-running the same change would put the probe back on 8080 and reproduce the stuck rollout. If the rollout still fails after the merge, the previous ReplicaSet (checkout-6f7df9c775) is still running, so service is not interrupted.
