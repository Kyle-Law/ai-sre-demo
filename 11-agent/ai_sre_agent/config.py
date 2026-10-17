"""Configuration, loaded from environment variables (see 11-agent/.env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value or ""


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    # LLM
    anthropic_api_key: str
    model: str
    max_turns: int

    # Kubernetes (read-only kubeconfig)
    kubeconfig: str
    kubectl_bin: str
    argocd_namespace: str

    # Grafana (Viewer service-account token) -> Prometheus queries + alert state
    grafana_url: str
    grafana_token: str
    grafana_prom_uid: str

    # Jira
    jira_base_url: str
    jira_email: str
    jira_api_token: str
    jira_project_key: str
    jira_triage_label: str
    jira_transition_start: str
    jira_transition_review: str
    jira_transition_done: str

    # GitHub (agent can open PRs, never merge). Either a GitHub App (preferred) or a token.
    github_token: str
    github_repo: str
    github_base_branch: str
    github_api_url: str
    github_reviewers: list[str] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    github_app_id: str = ""
    github_app_private_key_path: str = ""
    github_app_installation_id: str = ""  # optional: looked up from the repo when empty

    # Loop behaviour
    poll_seconds: int = 20
    verify_stable_seconds: int = 90
    verify_timeout_seconds: int = 900
    sync_timeout_seconds: int = 600
    max_attempts: int = 2

    # Storage / audit
    state_db: str = ".agent/state.db"
    audit_log: str = ".agent/audit.jsonl"

    # Safety
    dry_run: bool = False

    @property
    def github_web_url(self) -> str:
        api = self.github_api_url.rstrip("/")
        host = "https://github.com" if api == "https://api.github.com" else api.replace("/api/v3", "")
        return f"{host}/{self.github_repo}"

    @classmethod
    def from_env(cls) -> "Config":
        app_id = _env("GITHUB_APP_ID")
        if app_id and not _env("GITHUB_APP_PRIVATE_KEY_PATH"):
            raise SystemExit("GITHUB_APP_ID is set but GITHUB_APP_PRIVATE_KEY_PATH is missing")
        if not app_id and not _env("GITHUB_TOKEN"):
            raise SystemExit("Set GITHUB_APP_ID + GITHUB_APP_PRIVATE_KEY_PATH (GitHub App) or GITHUB_TOKEN")
        return cls(
            anthropic_api_key=_env("ANTHROPIC_API_KEY", required=True),
            model=_env("AGENT_MODEL", "claude-sonnet-5-5"),
            max_turns=int(_env("AGENT_MAX_TURNS", "30")),
            kubeconfig=_env("KUBECONFIG", "agent.kubeconfig"),
            kubectl_bin=_env("KUBECTL_BIN", "kubectl"),
            argocd_namespace=_env("ARGOCD_NAMESPACE", "argocd"),
            grafana_url=_env("GRAFANA_URL", required=True).rstrip("/"),
            grafana_token=_env("GRAFANA_TOKEN", required=True),
            grafana_prom_uid=_env("GRAFANA_PROM_UID", "prometheus"),
            jira_base_url=_env("JIRA_BASE_URL", required=True).rstrip("/"),
            jira_email=_env("JIRA_EMAIL", required=True),
            jira_api_token=_env("JIRA_API_TOKEN", required=True),
            jira_project_key=_env("JIRA_PROJECT_KEY", required=True),
            jira_triage_label=_env("JIRA_TRIAGE_LABEL", "ai-triage"),
            jira_transition_start=_env("JIRA_TRANSITION_START", "In Progress"),
            jira_transition_review=_env("JIRA_TRANSITION_REVIEW", "In Review"),
            jira_transition_done=_env("JIRA_TRANSITION_DONE", "Done"),
            github_token=_env("GITHUB_TOKEN"),
            github_app_id=app_id,
            github_app_private_key_path=_env("GITHUB_APP_PRIVATE_KEY_PATH"),
            github_app_installation_id=_env("GITHUB_APP_INSTALLATION_ID"),
            github_repo=_env("GITHUB_REPO", required=True),
            github_base_branch=_env("GITHUB_BASE_BRANCH", "main"),
            github_api_url=_env("GITHUB_API_URL", "https://api.github.com").rstrip("/"),
            github_reviewers=[r.strip() for r in _env("GITHUB_REVIEWERS", "").split(",") if r.strip()],
            allowed_paths=[p.strip() for p in _env("AGENT_ALLOWED_PATHS", "06-demo-app/manifests/").split(",") if p.strip()],
            poll_seconds=int(_env("POLL_SECONDS", "20")),
            verify_stable_seconds=int(_env("VERIFY_STABLE_SECONDS", "90")),
            verify_timeout_seconds=int(_env("VERIFY_TIMEOUT_SECONDS", "900")),
            sync_timeout_seconds=int(_env("SYNC_TIMEOUT_SECONDS", "600")),
            max_attempts=int(_env("MAX_ATTEMPTS", "2")),
            state_db=_env("STATE_DB", ".agent/state.db"),
            audit_log=_env("AUDIT_LOG", ".agent/audit.jsonl"),
            dry_run=_bool("DRY_RUN", False),
        )
