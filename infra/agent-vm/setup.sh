#!/usr/bin/env bash
# Agent VM setup (Ubuntu 22.04/24.04, 1 vCPU / 1-2 GB is plenty).
#   sudo ./infra/agent-vm/setup.sh /tmp/agent.kubeconfig /tmp/agent.env
#
# Creates an unprivileged "aisre" user, installs kubectl + the agent into a
# virtualenv, locks down credentials (0600) and starts a hardened systemd unit.
set -euo pipefail
cd "$(dirname "$0")/../.."

KUBECONFIG_SRC="${1:?usage: setup.sh <agent.kubeconfig> <agent.env>}"
ENV_SRC="${2:?usage: setup.sh <agent.kubeconfig> <agent.env>}"
[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

step "Packages"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git curl ca-certificates jq >/dev/null

step "kubectl"
if ! command -v kubectl >/dev/null; then
  ARCH=$(dpkg --print-architecture)
  VER=$(curl -fsSL https://dl.k8s.io/release/stable.txt)
  curl -fsSLo /usr/local/bin/kubectl "https://dl.k8s.io/release/${VER}/bin/linux/${ARCH}/kubectl"
  chmod 0755 /usr/local/bin/kubectl
fi
kubectl version --client | head -n1

step "Service user and directories"
id aisre >/dev/null 2>&1 || useradd --system --home /opt/ai-sre-agent --shell /usr/sbin/nologin aisre
install -d -o aisre -g aisre -m 0750 /opt/ai-sre-agent /var/lib/ai-sre-agent /var/log/ai-sre-agent
install -d -o root -g aisre -m 0750 /etc/ai-sre-agent

step "Agent code + virtualenv"
rm -rf /opt/ai-sre-agent/src
cp -r agent /opt/ai-sre-agent/src
python3 -m venv /opt/ai-sre-agent/venv
/opt/ai-sre-agent/venv/bin/pip install -q --upgrade pip
/opt/ai-sre-agent/venv/bin/pip install -q /opt/ai-sre-agent/src
chown -R aisre:aisre /opt/ai-sre-agent

step "Credentials (read-only kubeconfig + env file, mode 0640 root:aisre)"
install -o root -g aisre -m 0640 "$KUBECONFIG_SRC" /etc/ai-sre-agent/kubeconfig
install -o root -g aisre -m 0640 "$ENV_SRC" /etc/ai-sre-agent/agent.env
grep -q '^KUBECONFIG=' /etc/ai-sre-agent/agent.env || echo 'KUBECONFIG=/etc/ai-sre-agent/kubeconfig' >> /etc/ai-sre-agent/agent.env
grep -q '^KUBECTL_BIN=' /etc/ai-sre-agent/agent.env || echo 'KUBECTL_BIN=/usr/local/bin/kubectl' >> /etc/ai-sre-agent/agent.env

step "CLI helper"
cat > /usr/local/bin/ai-sre-agent <<'EOF'
#!/usr/bin/env bash
# Run the agent CLI as the service user with the service's environment.
# Usage: sudo ai-sre-agent selftest|status|diagnose INC-1|once
[[ $EUID -eq 0 ]] || exec sudo "$0" "$@"
set -a; source /etc/ai-sre-agent/agent.env; set +a
export KUBECACHEDIR=/var/lib/ai-sre-agent/kube-cache
exec sudo -E -u aisre /opt/ai-sre-agent/venv/bin/ai-sre-agent "$@"
EOF
chmod 0755 /usr/local/bin/ai-sre-agent

step "systemd unit"
install -m 0644 infra/agent-vm/ai-sre-agent.service /etc/systemd/system/ai-sre-agent.service
systemctl daemon-reload

step "Self-test (connectivity + RBAC proof)"
if ai-sre-agent selftest; then
  systemctl enable --now ai-sre-agent
  echo
  echo "Agent running. Follow it with:  journalctl -fu ai-sre-agent"
  echo "Audit trail:                    tail -f /var/log/ai-sre-agent/audit.jsonl | jq ."
else
  echo
  echo "Self-test failed: fix /etc/ai-sre-agent/agent.env, then: sudo systemctl enable --now ai-sre-agent" >&2
  exit 1
fi
