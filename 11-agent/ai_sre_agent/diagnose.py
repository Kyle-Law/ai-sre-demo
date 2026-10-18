"""The diagnosis loop: Claude + read-only tools -> a structured Diagnosis."""

from __future__ import annotations

import difflib
import json
import posixpath
import time
from dataclasses import dataclass, field

import yaml

from .audit import AuditLog
from .github import GitHub
from .grafana import Grafana, summarize_prom
from .kube import Kubectl, KubectlRefused
from .prompts import SYSTEM_PROMPT

FORBIDDEN_KINDS = {"Secret", "Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding", "ServiceAccount"}
MAX_CHANGED_LINES = 80

TOOLS = [
    {
        "name": "kubectl",
        "description": (
            "Run a READ-ONLY kubectl command against the cluster. Pass arguments as a list, without the "
            "'kubectl' prefix, e.g. [\"get\",\"pods\",\"-n\",\"shop\",\"-o\",\"wide\"], "
            "[\"describe\",\"pod\",\"checkout-abc\",\"-n\",\"shop\"], "
            "[\"logs\",\"deploy/checkout\",\"-n\",\"shop\",\"--previous\",\"--tail=80\"], "
            "[\"get\",\"events\",\"-n\",\"shop\",\"--sort-by=.lastTimestamp\"]. "
            "Allowed verbs: get, describe, logs, top, events, explain, api-resources, version, "
            "auth can-i, rollout status|history. Secrets are never readable."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"args": {"type": "array", "items": {"type": "string"}}},
            "required": ["args"],
        },
    },
    {
        "name": "promql",
        "description": "Run a PromQL query against Prometheus. Optionally a range query over the last N minutes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "range_minutes": {"type": "integer", "minimum": 1, "maximum": 1440},
            },
            "required": ["query"],
        },
    },
    {
        "name": "active_alerts",
        "description": "List Grafana-managed alerts currently pending or firing (optionally filtered by namespace).",
        "input_schema": {"type": "object", "properties": {"namespace": {"type": "string"}}},
    },
    {
        "name": "list_repo_dir",
        "description": "List files in a directory of the GitOps repository (main branch).",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "name": "read_repo_file",
        "description": "Read a file from the GitOps repository (main branch).",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "name": "recent_commits",
        "description": "Recent commits on main, optionally only those touching a path. Use to find regressions.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 30}},
        },
    },
    {
        "name": "commit_diff",
        "description": "Show the full diff and message of one commit.",
        "input_schema": {"type": "object", "properties": {"sha": {"type": "string"}}, "required": ["sha"]},
    },
    {
        "name": "submit_diagnosis",
        "description": (
            "Finish the investigation. Call exactly once. For action=pull_request include the COMPLETE new "
            "content of each changed file. For action=escalate leave changes empty and give next_steps."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "One or two sentences: what is broken and why."},
                "root_cause": {"type": "string"},
                "evidence": {"type": "array", "items": {"type": "string"},
                             "description": "Concrete observations backing the root cause (commands/output/commits)."},
                "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                "action": {"type": "string", "enum": ["pull_request", "escalate"]},
                "pr_title": {"type": "string", "description": "Short imperative PR title, e.g. 'Restore checkout memory limit to 256Mi'."},
                "changes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                        "required": ["path", "content"],
                    },
                },
                "risk": {"type": "string"},
                "rollback_plan": {"type": "string"},
                "verification_plan": {"type": "string"},
                "escalation_reason": {"type": "string"},
                "next_steps": {"type": "array", "items": {"type": "string"}},
                "offending_commit": {"type": "string", "description": "sha of the commit that introduced the problem, if any"},
                "reasoning_steps": {
                    "type": "array", "items": {"type": "string"},
                    "description": ("How you found the root cause, in the order you did it. One item per step: what you "
                                    "checked, what it showed, what that told you. End with the conclusion. 3-8 items."),
                },
            },
            "required": ["summary", "root_cause", "evidence", "confidence", "action", "reasoning_steps"],
        },
    },
]


@dataclass
class Diagnosis:
    summary: str
    root_cause: str
    evidence: list[str]
    confidence: str
    action: str
    pr_title: str = ""
    changes: list[dict] = field(default_factory=list)  # {path, content, original, diff}
    risk: str = ""
    rollback_plan: str = ""
    verification_plan: str = ""
    escalation_reason: str = ""
    next_steps: list[str] = field(default_factory=list)
    offending_commit: str = ""
    reasoning_steps: list[str] = field(default_factory=list)  # the model's account of how it got there
    investigation: list[dict] = field(default_factory=list)  # tool calls actually made: tool, input, t, result
    model: str = ""
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["changes"] = [{k: v for k, v in c.items() if k in ("path", "diff")} for c in self.changes]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Diagnosis":
        """Inverse of `self.__dict__` (full changes, file content included), used to hand a
        diagnosis from the investigator Job to the controller."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class Diagnoser:
    def __init__(self, cfg, kube: Kubectl, grafana: Grafana, github: GitHub, audit: AuditLog, client=None):
        self.cfg = cfg
        self.kube = kube
        self.grafana = grafana
        self.github = github
        self.audit = audit
        if client is None:
            import anthropic
            client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        self.client = client

    # -- tool execution ------------------------------------------------------
    def dispatch(self, ticket: str, name: str, args: dict) -> tuple[str, bool]:
        """Return (output, is_error)."""
        try:
            if name == "kubectl":
                code, out = self.kube.run(list(args.get("args", [])))
                return (f"exit={code}\n{out}", code != 0)
            if name == "promql":
                res = self.grafana.promql(args["query"], args.get("range_minutes"))
                return summarize_prom(res), False
            if name == "active_alerts":
                alerts = self.grafana.active_alerts()
                ns = args.get("namespace")
                if ns:
                    alerts = [a for a in alerts if a.get("labels", {}).get("namespace") == ns]
                slim = [{"labels": a.get("labels"), "state": a.get("state"), "activeAt": a.get("activeAt")} for a in alerts]
                return json.dumps(slim, indent=1)[:8000], False
            if name == "list_repo_dir":
                return "\n".join(self.github.list_dir(args["path"])), False
            if name == "read_repo_file":
                return self.github.read_file(args["path"])[:20000], False
            if name == "recent_commits":
                return json.dumps(self.github.recent_commits(args.get("path"), args.get("limit", 10)), indent=1), False
            if name == "commit_diff":
                return self.github.commit_diff(args["sha"])[:15000], False
            return f"unknown tool {name}", True
        except KubectlRefused as exc:
            return f"REFUSED by agent policy: {exc}", True
        except Exception as exc:  # surface the error to the model, keep going
            return f"ERROR: {exc}", True

    # -- validation of proposed changes ---------------------------------------
    def validate_changes(self, changes: list[dict]) -> tuple[list[dict], list[str]]:
        problems, validated = [], []
        for ch in changes or []:
            path = posixpath.normpath(str(ch.get("path", "")).lstrip("/"))
            content = ch.get("content", "")
            if ".." in path.split("/") or not any(path.startswith(p) for p in self.cfg.allowed_paths):
                problems.append(f"{path}: outside allowed paths {self.cfg.allowed_paths}")
                continue
            if not content.endswith("\n"):
                content += "\n"
            try:
                original = self.github.read_file(path)
            except Exception:
                original = ""
            if path.endswith((".yaml", ".yml")):
                try:
                    docs = [d for d in yaml.safe_load_all(content) if d]
                except yaml.YAMLError as exc:
                    problems.append(f"{path}: invalid YAML: {exc}")
                    continue
                bad = {d.get("kind") for d in docs if isinstance(d, dict)} & FORBIDDEN_KINDS
                if bad:
                    problems.append(f"{path}: the agent may not create/modify {sorted(bad)}")
                    continue
            if content == original:
                problems.append(f"{path}: proposed content is identical to the current file")
                continue
            diff = "".join(difflib.unified_diff(
                original.splitlines(keepends=True), content.splitlines(keepends=True),
                fromfile=f"a/{path}", tofile=f"b/{path}"))
            changed = sum(1 for l in diff.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---")))
            if changed > MAX_CHANGED_LINES:
                problems.append(f"{path}: {changed} changed lines; keep the fix minimal (<= {MAX_CHANGED_LINES})")
                continue
            validated.append({"path": path, "content": content, "original": original, "diff": diff})
        return validated, problems

    # -- main loop -----------------------------------------------------------
    def run(self, ticket: str, context: str) -> Diagnosis:
        system = SYSTEM_PROMPT.format(argocd_ns=self.cfg.argocd_namespace,
                                      allowed_paths=", ".join(self.cfg.allowed_paths))
        messages: list[dict] = [{"role": "user", "content": context}]
        investigation: list[dict] = []
        started = time.monotonic()
        usage_in = usage_out = cache_read = cache_write = 0
        max_turns = self.cfg.max_turns

        for turn in range(1, max_turns + 1):
            if turn == max_turns - 1:
                # Forcing a specific tool via tool_choice is rejected by current models, so ask instead.
                _append_user_text(messages, "Turn budget nearly used up: call submit_diagnosis now with what you "
                                            "have (action=escalate if you are not confident).")
            resp = self.client.beta.messages.create(
                model=self.cfg.model,
                max_tokens=8192,
                system=system,
                tools=TOOLS,
                tool_choice={"type": "auto"},
                messages=messages,
                # Every turn resends tools + system + transcript: cache that prefix.
                cache_control={"type": "ephemeral"},
                # Once the transcript grows large, clear stale tool output instead of resending it.
                betas=["context-management-2025-06-27"],
                context_management={"edits": [{"type": "clear_tool_uses_20250919"}]},
            )
            usage_in += getattr(resp.usage, "input_tokens", 0) or 0
            usage_out += getattr(resp.usage, "output_tokens", 0) or 0
            cache_read += getattr(resp.usage, "cache_read_input_tokens", 0) or 0
            cache_write += getattr(resp.usage, "cache_creation_input_tokens", 0) or 0
            messages.append({"role": "assistant", "content": resp.content})

            tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
            if not tool_uses:
                messages.append({"role": "user", "content": "Continue the investigation, then call submit_diagnosis."})
                continue

            results = []
            for tu in tool_uses:
                if tu.name == "submit_diagnosis":
                    diag, error = self._finalize(ticket, dict(tu.input), investigation)
                    if diag:
                        diag.model, diag.turns = self.cfg.model, turn
                        diag.input_tokens, diag.output_tokens = usage_in, usage_out
                        self._audit_usage(ticket, turn, usage_in, usage_out, cache_read, cache_write)
                        return diag
                    results.append({"type": "tool_result", "tool_use_id": tu.id, "content": error, "is_error": True})
                    continue
                output, is_error = self.dispatch(ticket, tu.name, dict(tu.input))
                investigation.append({"tool": tu.name, "input": dict(tu.input), "error": is_error,
                                      "t": round(time.monotonic() - started),   # seconds into the diagnosis
                                      "result": " ".join(output.split())[:160]})  # what it showed, abridged
                self.audit.write("tool_call", ticket=ticket, tool=tu.name, input=dict(tu.input),
                                 is_error=is_error, output=output[:4000])
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": output, "is_error": is_error})
            messages.append({"role": "user", "content": results})

        self._audit_usage(ticket, max_turns, usage_in, usage_out, cache_read, cache_write)
        return Diagnosis(
            summary="The agent did not reach a conclusion within its turn budget.",
            root_cause="unknown", evidence=[], confidence="low", action="escalate",
            escalation_reason="turn budget exhausted", investigation=investigation,
            model=self.cfg.model, turns=max_turns, input_tokens=usage_in, output_tokens=usage_out,
        )

    def _audit_usage(self, ticket: str, turns: int, uncached_in: int, out: int, cache_read: int, cache_write: int) -> None:
        """Token usage per diagnosis, for comparing models and cost (input_tokens excludes cached tokens)."""
        self.audit.write("model_usage", ticket=ticket, model=self.cfg.model, turns=turns, input_tokens=uncached_in,
                         output_tokens=out, cache_read_input_tokens=cache_read, cache_creation_input_tokens=cache_write)

    def _finalize(self, ticket: str, data: dict, investigation: list[dict]) -> tuple[Diagnosis | None, str]:
        action = data.get("action", "escalate")
        changes, problems = ([], [])
        if action == "pull_request":
            changes, problems = self.validate_changes(data.get("changes", []))
            if problems:
                self.audit.write("diagnosis_rejected", ticket=ticket, problems=problems)
                return None, ("Your proposed changes were rejected, fix them and call submit_diagnosis again:\n- "
                              + "\n- ".join(problems))
            if not changes:
                return None, "action=pull_request requires at least one valid file change (or use action=escalate)."
        diag = Diagnosis(
            summary=data.get("summary", ""),
            root_cause=data.get("root_cause", ""),
            evidence=list(data.get("evidence", [])),
            confidence=data.get("confidence", "low"),
            action=action,
            pr_title=data.get("pr_title") or "Remediate incident",
            changes=changes,
            risk=data.get("risk", ""),
            rollback_plan=data.get("rollback_plan", ""),
            verification_plan=data.get("verification_plan", ""),
            escalation_reason=data.get("escalation_reason", ""),
            next_steps=list(data.get("next_steps", [])),
            offending_commit=data.get("offending_commit", ""),
            reasoning_steps=[str(s) for s in data.get("reasoning_steps", [])],
            investigation=investigation,
        )
        self.audit.write("diagnosis", ticket=ticket, **{k: v for k, v in diag.to_dict().items() if k != "investigation"})
        return diag, ""


def _append_user_text(messages: list[dict], text: str) -> None:
    """Add a note to the newest user turn (it may hold tool_result blocks)."""
    last = messages[-1]
    if isinstance(last["content"], str):
        last["content"] += "\n\n" + text
    else:
        last["content"].append({"type": "text", "text": text})
