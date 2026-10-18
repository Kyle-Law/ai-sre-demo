"""Read-only kubectl wrapper.

Runs only inside the cluster, as the pod's ServiceAccount (step 12). Defence in depth: that
ServiceAccount's RBAC already denies every write, but the agent also refuses to *attempt*
anything outside a small read-only allowlist, never reads Secrets, and never lets the model
point kubectl elsewhere.
"""

from __future__ import annotations

import json
import os
import subprocess

READ_ONLY_VERBS = {"get", "describe", "logs", "top", "events", "explain", "api-resources", "version"}
# verb -> allowed sub-commands
READ_ONLY_SUBCOMMANDS = {"auth": {"can-i"}, "rollout": {"status", "history"}}

FORBIDDEN_FLAGS = (
    "--kubeconfig", "--context", "--cluster", "--user", "--token", "--server", "-s",
    "--as", "--as-group", "--as-uid", "--insecure-skip-tls-verify", "--username", "--password",
    "--client-certificate", "--client-key", "--certificate-authority", "--raw",
    "-w", "--watch", "--watch-only", "-f", "--follow",
)
SECRET_RESOURCES = {"secret", "secrets"}
MAX_OUTPUT_CHARS = 12_000


class KubectlRefused(Exception):
    """Raised when a kubectl invocation is outside the read-only allowlist."""


def validate_args(args: list[str]) -> None:
    if not args or not all(isinstance(a, str) for a in args):
        raise KubectlRefused("kubectl needs a non-empty list of string arguments")
    verb = args[0]
    if verb in READ_ONLY_SUBCOMMANDS:
        if len(args) < 2 or args[1] not in READ_ONLY_SUBCOMMANDS[verb]:
            raise KubectlRefused(f"only 'kubectl {verb} {'|'.join(sorted(READ_ONLY_SUBCOMMANDS[verb]))}' is allowed")
    elif verb not in READ_ONLY_VERBS:
        raise KubectlRefused(f"verb '{verb}' is not read-only; allowed: {sorted(READ_ONLY_VERBS | set(READ_ONLY_SUBCOMMANDS))}")

    for arg in args[1:]:
        flag = arg.split("=", 1)[0]
        if flag in FORBIDDEN_FLAGS:
            raise KubectlRefused(f"flag '{flag}' is not allowed")
        if arg.startswith("-") or verb == "auth":  # "auth can-i get secrets" only asks a question
            continue
        # e.g. "secrets", "secret/foo", "pods,secrets", "secrets.v1"
        for part in arg.lower().replace("/", ",").split(","):
            if part.split(".", 1)[0] in SECRET_RESOURCES:
                raise KubectlRefused("reading Secrets is never allowed for the agent")


def in_cluster() -> bool:
    return bool(os.environ.get("KUBERNETES_SERVICE_HOST"))


class Kubectl:
    def __init__(self, kubectl_bin: str = "kubectl", timeout: int = 30):
        self.kubectl_bin = kubectl_bin
        self.timeout = timeout

    def run(self, args: list[str], *, validate: bool = True, full: bool = False) -> tuple[int, str]:
        """Return (exit_code, combined_output). Never raises for kubectl errors.
        Output is truncated for the model unless full=True (for output the agent parses itself)."""
        if validate:
            validate_args(args)
        # Outside a pod kubectl would fall back to ~/.kube/config: your admin credentials.
        if not in_cluster():
            return 1, "kubectl runs only inside the cluster, as the agent's ServiceAccount (step 12)"
        # No KUBECONFIG and no connection flags (even --request-timeout): either one stops kubectl
        # from using the pod's ServiceAccount token. The subprocess timeout still applies.
        env = {k: v for k, v in os.environ.items() if k != "KUBECONFIG"}
        try:
            proc = subprocess.run([self.kubectl_bin, *args], env=env, capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return 124, f"kubectl timed out after {self.timeout}s"
        except FileNotFoundError:
            return 127, f"kubectl binary not found: {self.kubectl_bin}"
        output = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        return proc.returncode, output if full else truncate(output)

    def get_json(self, args: list[str]) -> dict | None:
        # Untruncated: a cut-off JSON document doesn't parse (the Application list is >100 KB).
        code, out = self.run([*args, "-o", "json"], full=True)
        if code != 0:
            return None
        try:
            return json.loads(out.split("\n[stderr]\n", 1)[0])
        except json.JSONDecodeError:
            return None


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit // 3]
    tail = text[-(2 * limit // 3):]
    return f"{head}\n... [{len(text) - limit} chars truncated] ...\n{tail}"
