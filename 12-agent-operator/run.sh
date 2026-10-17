#!/usr/bin/env bash
# Step 12: run the agent inside the cluster - controller + one diagnosis Job per ticket.
#   DRY_RUN=true make step-12     # controller investigates and logs, writes nothing to Jira/GitHub
source "$(dirname "$0")/../lib/common.sh"
need_bin docker kind
need_context
need_namespace ai-sre 08
[[ -f agent.env ]] || die "agent.env missing - do step 11 first"
need_pushed 12-agent-operator 11-agent

step "Image ai-sre-agent:dev (built locally, loaded into kind - no registry)"
docker build --load -q -t ai-sre-agent:dev 11-agent
kind load docker-image ai-sre-agent:dev --name "$CLUSTER"

step "Secrets from agent.env (never in git)"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
# Split agent.env: the controller gets everything (it does the Jira/GitHub writes);
# the investigator Jobs only get the model key and the Grafana Viewer token.
python3 - "$tmp" <<'EOF'
import os, pathlib, sys
out = pathlib.Path(sys.argv[1])
env = {}
for line in pathlib.Path("agent.env").read_text().splitlines():
    key, sep, value = line.partition("=")
    key, value = key.strip(), value.strip()
    if not sep or key.startswith("#"):
        continue
    if value[:1] in "\"'" and value[-1:] == value[:1]:
        value = value[1:-1]
    else:
        value = value.split(" #", 1)[0].strip()
    env[key] = value
if os.environ.get("DRY_RUN"):
    env["DRY_RUN"] = os.environ["DRY_RUN"]
local_only = {"KUBECONFIG", "KUBECTL_BIN", "STATE_DB", "AUDIT_LOG", "GRAFANA_URL", "GITHUB_APP_PRIVATE_KEY_PATH"}
key_path = env.get("GITHUB_APP_PRIVATE_KEY_PATH", "github-app.pem")
(out / "controller.env").write_text("".join(f"{k}={v}\n" for k, v in env.items() if k not in local_only and v))
(out / "investigator.env").write_text("".join(f"{k}={env.get(k, '')}\n" for k in ("ANTHROPIC_API_KEY", "GRAFANA_TOKEN")))
(out / "key_path").write_text(os.path.expanduser(key_path))
EOF
key_path=$(cat "$tmp/key_path")
[[ -f "$key_path" ]] || die "GitHub App key $key_path not found (step 10)"
kubectl create namespace ai-sre-agent --dry-run=client -o yaml | kubectl apply -f -
kubectl -n ai-sre-agent create secret generic controller-credentials --from-env-file="$tmp/controller.env" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n ai-sre-agent create secret generic agent-github-app --from-file=github-app.pem="$key_path" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n ai-sre create secret generic investigator-credentials --from-env-file="$tmp/investigator.env" \
  --dry-run=client -o yaml | kubectl apply -f -

step "ArgoCD Application 'agent-operator'"
kubectl apply -f 12-agent-operator/application.yaml
wait_app agent-operator 300
# Same image tag after a rebuild, and Secrets may have changed: replace the pod.
kubectl -n ai-sre-agent delete pod -l app=agent-controller --wait=false >/dev/null
kubectl -n ai-sre-agent rollout status deploy/agent-controller --timeout=180s

cat <<EOF

The agent now runs in the cluster. Stop any local agent (make step-11): both would
handle the same tickets.
  kubectl -n ai-sre-agent get agentsessions -w            # incident board
  kubectl -n ai-sre-agent logs deploy/agent-controller -f # controller log
  kubectl -n ai-sre get jobs -l app=ai-sre-investigator   # diagnosis Jobs
Next: make verify-12
EOF
