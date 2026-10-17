"""In-cluster mode (step 12): the same workflow, with two parts swapped out.

* CRStateStore - incident state lives in one AgentSession custom resource per ticket
  instead of a local SQLite file, so `kubectl get agentsessions` is the incident board.
* JobDiagnoser - every LLM diagnosis runs as a short-lived Job under the read-only
  ServiceAccount. The Job holds no Jira or GitHub write credentials; it prints its
  Diagnosis and exits. Only this controller (deterministic code) writes to Jira/GitHub.

Kubernetes is driven with plain `kubectl` (already in the image), not a client library.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time

from .audit import AuditLog
from .diagnose import Diagnosis
from .state import NEW, now_iso

log = logging.getLogger("ai_sre_agent")

GROUP_VERSION = "ai-sre.demo/v1alpha1"
RESULT_MARKER = "AGENT_RESULT "


class KubectlError(RuntimeError):
    pass


def kubectl(*args: str, stdin: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["kubectl", *args], input=stdin, capture_output=True, text=True, timeout=60)
    if check and proc.returncode != 0:
        raise KubectlError(f"kubectl {' '.join(args[:3])}: {proc.stderr.strip()[:400]}")
    return proc


def session_name(key: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", key.lower())


class CRStateStore:
    """StateStore interface backed by AgentSession resources (state in .status)."""

    def __init__(self, namespace: str):
        self.ns = namespace

    def _status(self, obj: dict) -> dict:
        data = dict(obj.get("status") or {})
        data.setdefault("stage", NEW)
        data["key"] = obj["spec"]["ticket"]
        return data

    def get(self, key: str) -> dict | None:
        proc = kubectl("-n", self.ns, "get", "agentsession", session_name(key), "-o", "json", check=False)
        if proc.returncode != 0:
            if "NotFound" in proc.stderr:
                return None
            raise KubectlError(proc.stderr.strip()[:400])
        return self._status(json.loads(proc.stdout))

    def put(self, key: str, stage: str, data: dict) -> dict:
        name = session_name(key)
        status = {k: v for k, v in data.items() if k not in {"key"} and v is not None}
        status.update(stage=stage, updatedAt=now_iso())
        kubectl("-n", self.ns, "apply", "-f", "-", stdin=json.dumps({
            "apiVersion": GROUP_VERSION, "kind": "AgentSession",
            "metadata": {"name": name, "namespace": self.ns, "labels": {"ai-sre.demo/ticket": name}},
            "spec": {"ticket": key},
        }))
        # JSON-patch "add" on /status replaces the whole status, matching StateStore.put.
        kubectl("-n", self.ns, "patch", "agentsession", name, "--subresource=status", "--type=json",
                "-p", json.dumps([{"op": "add", "path": "/status", "value": status}]))
        return {**status, "key": key}

    def update(self, key: str, stage: str | None = None, **fields) -> dict:
        current = self.get(key) or {}
        current.update(fields)
        return self.put(key, stage or current.get("stage", NEW), current)

    def all(self) -> list[dict]:
        items = json.loads(kubectl("-n", self.ns, "get", "agentsessions", "-o", "json").stdout)["items"]
        rows = [self._status(o) for o in items]
        return sorted(rows, key=lambda r: r.get("updatedAt", ""), reverse=True)

    def in_stage(self, *stages: str) -> list[dict]:
        return [r for r in self.all() if r["stage"] in stages]


class JobDiagnoser:
    """Diagnoser interface: run(ticket, context) -> Diagnosis, executed in a Job."""

    def __init__(self, cfg, audit: AuditLog, namespace: str, image: str, service_account: str,
                 timeout_seconds: int = 900):
        self.cfg, self.audit = cfg, audit
        self.ns, self.image, self.sa = namespace, image, service_account
        self.timeout = timeout_seconds

    def job_manifest(self, name: str, ticket: str, context: str) -> dict:
        env = {
            "AGENT_ROLE": "investigator", "AGENT_TICKET": ticket, "AGENT_CONTEXT": context,
            "AGENT_MODEL": self.cfg.model, "AGENT_MAX_TURNS": str(self.cfg.max_turns),
            "AGENT_ALLOWED_PATHS": ",".join(self.cfg.allowed_paths), "ARGOCD_NAMESPACE": self.cfg.argocd_namespace,
            "GITHUB_REPO": self.cfg.github_repo, "GITHUB_BASE_BRANCH": self.cfg.github_base_branch,
            "GRAFANA_URL": self.cfg.grafana_url, "GRAFANA_PROM_UID": self.cfg.grafana_prom_uid,
            "KUBECONFIG": "", "HOME": "/tmp", "KUBECACHEDIR": "/tmp/kube-cache", "AUDIT_LOG": "/tmp/audit.jsonl",
        }
        return {
            "apiVersion": "batch/v1", "kind": "Job",
            "metadata": {"name": name, "namespace": self.ns,
                         "labels": {"app": "ai-sre-investigator", "ai-sre.demo/ticket": session_name(ticket)}},
            "spec": {
                "backoffLimit": 0,
                "activeDeadlineSeconds": self.timeout,
                "ttlSecondsAfterFinished": 3600,
                "template": {
                    "metadata": {"labels": {"app": "ai-sre-investigator", "ai-sre.demo/ticket": session_name(ticket)}},
                    "spec": {
                        "serviceAccountName": self.sa,
                        # The step 09 ServiceAccount disables token automount (it's meant for an
                        # external kubeconfig); this pod needs its token to call the API.
                        "automountServiceAccountToken": True,
                        "restartPolicy": "Never",
                        "priorityClassName": "ai-sre-critical",
                        # Must still schedule when the incident IS a cordoned node (scenario 06).
                        "tolerations": [{"key": "node.kubernetes.io/unschedulable", "operator": "Exists",
                                         "effect": "NoSchedule"}],
                        "securityContext": {"runAsNonRoot": True, "runAsUser": 65532,
                                            "seccompProfile": {"type": "RuntimeDefault"}},
                        "containers": [{
                            "name": "investigator", "image": self.image, "imagePullPolicy": "IfNotPresent",
                            "args": ["investigate"],
                            "env": [{"name": k, "value": v} for k, v in env.items()],
                            # Only the model key and a Grafana *Viewer* token.
                            "envFrom": [{"secretRef": {"name": "investigator-credentials"}}],
                            "resources": {"requests": {"cpu": "50m", "memory": "128Mi"},
                                          "limits": {"memory": "512Mi"}},
                            "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                                                "capabilities": {"drop": ["ALL"]}},
                            "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],
                        }],
                        "volumes": [{"name": "tmp", "emptyDir": {}}],
                    },
                },
            },
        }

    def run(self, ticket: str, context: str) -> Diagnosis:
        name = f"diagnose-{session_name(ticket)}-{int(time.time())}"[:63]
        kubectl("create", "-f", "-", stdin=json.dumps(self.job_manifest(name, ticket, context)))
        self.audit.write("investigator_started", ticket=ticket, job=f"{self.ns}/{name}")
        deadline = time.time() + self.timeout + 60
        while time.time() < deadline:
            status = json.loads(kubectl("-n", self.ns, "get", "job", name, "-o", "json").stdout).get("status", {})
            if status.get("succeeded") or status.get("failed"):
                break
            time.sleep(5)
        logs = kubectl("-n", self.ns, "logs", f"job/{name}", "--tail=-1", check=False).stdout
        result = next((l[len(RESULT_MARKER):] for l in reversed(logs.splitlines()) if l.startswith(RESULT_MARKER)), None)
        self.audit.write("investigator_finished", ticket=ticket, job=f"{self.ns}/{name}", ok=bool(result))
        if not result:
            tail = "\n".join(logs.splitlines()[-15:])
            raise RuntimeError(f"investigator job {self.ns}/{name} produced no diagnosis. Log tail:\n{tail}")
        return Diagnosis.from_dict(json.loads(result))


def operator_settings() -> dict:
    return {
        "session_namespace": os.environ.get("OPERATOR_NAMESPACE", "ai-sre-agent"),
        "job_namespace": os.environ.get("INVESTIGATOR_NAMESPACE", "ai-sre"),
        "image": os.environ.get("INVESTIGATOR_IMAGE", "ai-sre-agent:dev"),
        "service_account": os.environ.get("INVESTIGATOR_SERVICE_ACCOUNT", "ai-sre-agent"),
    }
