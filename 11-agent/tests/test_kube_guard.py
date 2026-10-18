import pytest

from ai_sre_agent.kube import KubectlRefused, truncate, validate_args


@pytest.mark.parametrize("args", [
    ["get", "pods", "-n", "shop", "-o", "wide"],
    ["describe", "pod", "checkout-abc", "-n", "shop"],
    ["logs", "deploy/checkout", "-n", "shop", "--previous", "--tail=80"],
    ["get", "events", "-n", "shop", "--sort-by=.lastTimestamp"],
    ["top", "pods", "-n", "shop"],
    ["rollout", "history", "deployment/checkout", "-n", "shop"],
    ["auth", "can-i", "get", "secrets", "-n", "shop"],  # asking is fine
    ["get", "applications.argoproj.io", "-n", "argocd", "-o", "yaml"],
])
def test_read_only_commands_allowed(args):
    validate_args(args)


@pytest.mark.parametrize("args", [
    ["delete", "pod", "x"],
    ["apply", "-f", "x.yaml"],
    ["patch", "deployment", "checkout", "-p", "{}"],
    ["scale", "deployment/checkout", "--replicas=0"],
    ["exec", "-it", "pod", "--", "sh"],
    ["edit", "deployment", "checkout"],
    ["rollout", "restart", "deployment/checkout"],
    ["rollout", "undo", "deployment/checkout"],
    ["auth", "reconcile", "-f", "x"],
    ["get", "secrets", "-n", "shop"],
    ["get", "secret/db-password", "-n", "shop"],
    ["get", "pods,secrets", "-A"],
    ["describe", "secrets.v1", "-n", "shop"],
    ["get", "pods", "--kubeconfig=/etc/admin"],
    ["get", "pods", "--as=system:admin"],
    ["get", "pods", "--server", "https://evil"],
    ["logs", "-f", "deploy/checkout"],
    ["get", "pods", "-w"],
    ["get", "--raw", "/api/v1/secrets"],
    [],
])
def test_mutating_or_sensitive_commands_refused(args):
    with pytest.raises(KubectlRefused):
        validate_args(args)


def test_truncate_keeps_head_and_tail():
    text = "A" * 10_000 + "B" * 10_000
    out = truncate(text, limit=3000)
    assert out.startswith("A") and out.endswith("B") and "truncated" in out
    assert len(out) < 3200



def test_uses_the_pods_service_account_only(monkeypatch):
    """No KUBECONFIG and no connection flags (even --request-timeout): either one stops kubectl
    from using the pod's ServiceAccount token."""
    from ai_sre_agent import kube
    seen = []
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.96.0.1")
    monkeypatch.setenv("KUBECONFIG", "/home/me/.kube/admin")
    monkeypatch.setattr(kube.subprocess, "run", lambda cmd, env, **kw: seen.append((cmd, env)) or
                        kube.subprocess.CompletedProcess(cmd, 0, "", ""))
    kube.Kubectl().run(["get", "pods", "-n", "shop"])
    cmd, env = seen[0]
    assert cmd == ["kubectl", "get", "pods", "-n", "shop"] and "KUBECONFIG" not in env


def test_refuses_to_run_outside_the_cluster(monkeypatch):
    """On a laptop kubectl would fall back to ~/.kube/config: the admin's credentials."""
    from ai_sre_agent import kube
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    monkeypatch.setattr(kube.subprocess, "run", lambda *a, **kw: pytest.fail("kubectl was called"))
    code, out = kube.Kubectl().run(["get", "pods", "-n", "shop"])
    assert code == 1 and "only inside the cluster" in out


def test_get_json_parses_output_longer_than_the_model_limit(monkeypatch):
    """The ArgoCD Application list is >100 KB; truncating it broke sync detection."""
    import json
    from ai_sre_agent import kube
    big = json.dumps({"items": [{"metadata": {"name": f"app-{i}"}, "pad": "x" * 500} for i in range(400)]})
    assert len(big) > kube.MAX_OUTPUT_CHARS
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.96.0.1")
    monkeypatch.setattr(kube.subprocess, "run", lambda cmd, **kw: kube.subprocess.CompletedProcess(cmd, 0, big, ""))
    k = kube.Kubectl()
    assert len(k.get_json(["get", "applications.argoproj.io", "-n", "argocd"])["items"]) == 400
    assert len(k.run(["get", "pods"])[1]) < len(big)          # what the model sees stays truncated
