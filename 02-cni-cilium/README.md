# 02 · CNI: Cilium

**Goal:** give the cluster a pod network. The node goes from NotReady to Ready, CoreDNS starts, and
NetworkPolicies are enforced from now on.

## Concepts

- **CNI (Container Network Interface)**: the plugin that gives every pod an IP and routes traffic
  between pods. Without one, the kubelet reports `NetworkReady=false` and nothing schedulable runs.
- **Cilium** implements the pod network and NetworkPolicy with eBPF programs in the kernel instead of
  iptables chains.
- **Hubble** is Cilium's flow log. It shows every connection, with source and destination pods, and
  marks the ones a policy dropped.
- **Why it matters here:** step 08 has a NetworkPolicy so that only Grafana can post alerts to the
  Jira bridge. That policy is only real if the CNI enforces it.

Settings are in [values.yaml](values.yaml); the version is pinned in [run.sh](run.sh)
(`CILIUM_VERSION`).

## Run

```bash
make step-02        # helm upgrade --install cilium ... --wait
make verify-02      # agent status, node Ready, DNS + service reachability from a test pod
```

## Look around

```bash
kubectl get nodes                                        # Ready
kubectl -n kube-system get pods -l k8s-app=cilium -o wide
kubectl -n kube-system exec ds/cilium -c cilium-agent -- cilium-dbg status
kubectl -n kube-system exec ds/cilium -c cilium-agent -- cilium-dbg endpoint list   # one per pod
kubectl -n kube-system port-forward svc/hubble-ui 12000:80                         # http://localhost:12000
```

In the Hubble UI, pick the `kube-system` namespace and watch CoreDNS traffic. After step 08, pick
`ai-sre` to see Grafana → alert-bridge flows, and the drops when anything else tries.

**Next:** [03 · metrics-server](../03-metrics-server/)
