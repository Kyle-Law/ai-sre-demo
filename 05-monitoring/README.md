# 05 · Monitoring: Prometheus + Grafana

**Goal:** the first ArgoCD Application. You get Prometheus collecting cluster state, and Grafana as
the alerting engine and UI.

## Concepts

- **kube-prometheus-stack** bundles Prometheus, the Prometheus Operator, kube-state-metrics and
  Grafana. [application.yaml](application.yaml) uses ArgoCD **multi-source**: the chart comes from
  the prometheus-community Helm repo (pinned version), and [values.yaml](values.yaml) comes from your
  git repo.
- **kube-state-metrics** turns Kubernetes object state into metrics, e.g.
  `kube_pod_container_status_waiting_reason{reason="ImagePullBackOff"}`. Every alert in step 07 is
  built on these.
- **Grafana-managed alerting** is used instead of Alertmanager (`alertmanager.enabled: false`), and
  `defaultRules.create: false` keeps the demo quiet: only our own rules raise tickets.
- **Secrets stay out of git**: `run.sh` creates the `grafana-admin` Secret from `demo.env` before the
  Application syncs, and the chart references it via `admin.existingSecret`.
- **Trimmed for kind**: scrapers for etcd, the scheduler, the controller-manager and kube-proxy are off
  (on kind they listen on 127.0.0.1 only). node-exporter is off (unused, and it fails on Docker
  Desktop).

## Run

```bash
make step-05        # creates the Secret, applies the Application, waits (~3-5 min)
make verify-05
```

## Look around

- ArgoCD UI → `monitoring`: the resource tree of a Helm release rendered by ArgoCD.
- Grafana <http://localhost:30300> → Explore → Prometheus. Try:
  ```promql
  kube_pod_info{namespace="kube-system"}
  sum by (namespace) (kube_pod_container_status_restarts_total)
  ```
- Change something in `values.yaml` (e.g. `retention: 3d` → `2d`), push, and watch ArgoCD sync it.

**Next:** [06 · Demo app](../06-demo-app/)
