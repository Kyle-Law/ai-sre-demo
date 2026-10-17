# 03 · metrics-server

**Goal:** turn on the Kubernetes resource metrics API, so `kubectl top` works for you and for the
AI agent.

## Concepts

- **Resource metrics API (`metrics.k8s.io`)**: live CPU and memory per node and pod, scraped from
  each kubelet. It backs `kubectl top` and the HorizontalPodAutoscaler.
- **metrics-server vs Prometheus**: metrics-server keeps only the latest sample, in memory. Prometheus
  (step 05) keeps history and powers alerts. The agent uses both: `kubectl top` for "right now",
  PromQL for "what happened".
- **API aggregation**: metrics-server registers an `APIService`, so the API server proxies
  `/apis/metrics.k8s.io` to it. The agent's read-only role (step 09) is granted `get` on
  `pods.metrics.k8s.io` like any other resource.
- **`--kubelet-insecure-tls`**: kind's kubelets use self-signed serving certificates. Fine for a laptop,
  not for production.

## Run

```bash
make step-03
make verify-03
```

## Look around

```bash
kubectl top nodes
kubectl top pods -A --sort-by=memory
kubectl get apiservice v1beta1.metrics.k8s.io
kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes | python3 -m json.tool | head -30
```

**Next:** [04 · ArgoCD](../04-argocd/)
