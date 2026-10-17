# 01 · kind cluster

**Goal:** a single-node Kubernetes cluster running in Docker, with Grafana's and ArgoCD's ports
reachable from your Mac, and **no pod network yet**.

## Concepts

- **kind** runs each Kubernetes node as a Docker container. `kind-ai-sre` becomes your kubectl
  context.
- **NodePorts and `extraPortMappings`**: services of type NodePort listen on the node container.
  [cluster.yaml](cluster.yaml) maps 30300 (Grafana) and 30443 (ArgoCD) from that container to
  `127.0.0.1` on your Mac.
- **`disableDefaultCNI: true`**: kind normally installs its own simple CNI (kindnet). We turn it off
  so step 02 can install Cilium and you can see what a cluster without a CNI looks like.

## Run

```bash
make step-01        # ./01-kind-cluster/run.sh
make verify-01
```

## Look around

```bash
kubectl get nodes                       # STATUS NotReady: no CNI
kubectl describe node ai-sre-control-plane | grep -A2 'Ready '
#   "container runtime network not ready: ... cni plugin not initialized"
kubectl -n kube-system get pods         # coredns stays Pending: no pod network to join
docker ps --filter name=ai-sre          # the "node" is just a container
```

Every later step refuses to run unless the current context is `kind-ai-sre`, so a step script can't
accidentally hit another cluster.

## Undo

`make down` deletes the cluster (all steps). Re-running `make step-01` on an existing cluster does
nothing.

**Next:** [02 · CNI (Cilium)](../02-cni-cilium/)
