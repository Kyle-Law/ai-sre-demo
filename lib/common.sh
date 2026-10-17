# Shared helpers for the step scripts. Source it from a step's run.sh / verify.sh:
#   source "$(dirname "$0")/../lib/common.sh"
# Loads demo.env (or $DEMO_ENV), and cds to the repo root.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f "${DEMO_ENV:-$ROOT/demo.env}" ]]; then
  # shellcheck disable=SC1090
  source "${DEMO_ENV:-$ROOT/demo.env}"
fi
CLUSTER="${KIND_CLUSTER_NAME:-ai-sre}"
KCTX="kind-${CLUSTER}"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die() { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# verify.sh helpers: check "<description>" <command...>
_ok=0; _bad=0
check() {
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then _ok=$((_ok+1)); printf '  \033[32mOK\033[0m   %s\n' "$desc"
  else _bad=$((_bad+1)); printf '  \033[31mFAIL\033[0m %s\n' "$desc"; fi
}
summary() {
  echo
  if [[ $_bad -eq 0 ]]; then printf '\033[32mAll %d checks passed.\033[0m\n' "$_ok"
  else printf '\033[31m%d of %d checks failed.\033[0m\n' "$_bad" $((_ok+_bad)); exit 1; fi
}

need() { for v in "$@"; do [[ -n "${!v:-}" ]] || die "set $v in demo.env"; done; }
need_bin() { for b in "$@"; do command -v "$b" >/dev/null || die "$b not found (brew install $b)"; done; }

# Every step after 01 talks to the demo cluster through the current kubectl
# context. Refuse to run against anything else (e.g. a work cluster).
need_context() {
  local cur
  cur=$(kubectl config current-context 2>/dev/null || true)
  [[ "$cur" == "$KCTX" ]] || die "kubectl context is '${cur:-unset}', expected '$KCTX'. Run: kubectl config use-context $KCTX"
}

need_namespace() { kubectl get namespace "$1" >/dev/null 2>&1 || die "namespace $1 missing - run step $2 first"; }

need_pushed() {  # ArgoCD deploys from GitHub, not from this working copy
  if grep -rq 'YOUR_GITHUB_ORG' --include=application.yaml "$ROOT"; then
    die "run 00-prereqs/configure-repo.sh and push to GitHub first"
  fi
  if git rev-parse -q --verify '@{u}' >/dev/null && [[ -n "$(git log '@{u}..' --oneline -- "$@" 2>/dev/null)" ]]; then
    echo "WARNING: unpushed commits touch $* - ArgoCD only sees what is on GitHub." >&2
  fi
}

app_status() { kubectl -n argocd get application "$1" -o jsonpath='{.status.sync.status}/{.status.health.status}' 2>/dev/null || true; }
app_healthy() { [[ "$(app_status "$1")" == "Synced/Healthy" ]]; }

wait_app() {  # wait_app <name> [timeout_seconds]
  local app="$1" timeout="${2:-600}" status="" waited=0
  info "waiting for ArgoCD app '$app' to be Synced/Healthy (up to ${timeout}s)"
  while (( waited < timeout )); do
    status=$(app_status "$app")
    [[ "$status" == "Synced/Healthy" ]] && { info "$app: $status"; return 0; }
    sleep 10; waited=$((waited+10))
  done
  die "$app is '${status:-unknown}' after ${timeout}s - check the ArgoCD UI (https://localhost:30443)"
}

grafana_api() {  # grafana_api <path> [curl args...]
  local path="$1"; shift
  curl -fsS -u "${GRAFANA_ADMIN_USER:-admin}:${GRAFANA_ADMIN_PASSWORD}" "${GRAFANA_URL:-http://localhost:30300}${path}" "$@"
}
