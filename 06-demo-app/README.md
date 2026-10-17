# 06 · Demo app: `checkout`

**Goal:** deploy the workload that will break (step 12) and that the AI agent will fix (step 11),
inside an ArgoCD **AppProject** that limits what any merged change can do.

## Concepts

- **The app** is [podinfo](https://github.com/stefanprodan/podinfo), a tiny Go web service, running as
  `checkout` in namespace `shop`. On start it loads a simulated ~96 MB catalog cache, so a too-small
  memory limit really OOMKills it.
- **`manifests/` is the agent's only write target.** The agent's config (`AGENT_ALLOWED_PATHS`) and
  the CI scope guard (step 10) both restrict agent PRs to `06-demo-app/manifests/` and `incidents/`.
- **AppProject as a guardrail** ([appproject.yaml](appproject.yaml)): Applications in project `shop`
  can only deploy into namespace `shop`, and can never create Secrets, Roles, RoleBindings,
  ServiceAccounts or cluster-scoped objects (except the `shop` Namespace). Even a human-approved bad
  PR can't escalate privileges through ArgoCD.
- **`demo.ai-sre/remediation-target: "true"`** on the Application labels it as a valid fix target
  for the agent.

## Run

```bash
make step-06
make verify-06
```

## Look around

```bash
kubectl -n shop get deploy checkout -o yaml | less       # resources, probes, env from ConfigMap
kubectl -n shop port-forward svc/checkout 9898:80        # http://localhost:9898
kubectl top pods -n shop                                 # ~100 MB each: the cache (step 03 at work)
```

Try the guardrail: add a `Secret` to `manifests/`, push, and watch ArgoCD refuse to sync it
(`resource :Secret is not permitted in project shop`). Then revert.

**Next:** [07 · Alert rules](../07-alert-rules/)
