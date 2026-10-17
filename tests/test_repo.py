"""Repo-level checks: the numbered step layout is complete, manifests parse, kustomize resource
lists resolve, ArgoCD Applications point at real paths, every scenario applies cleanly to the
baseline and produces valid YAML, and placeholders are consistent."""

import importlib.util
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("demo", ROOT / "13-scenarios/demo.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


def baseline_text(rel: str) -> str:
    """Demo-app files as of the demo-baseline tag when it exists, so these tests still pass
    while a scenario is injected (the working tree is deliberately broken then)."""
    res = subprocess.run(["git", "show", f"demo-baseline:{rel}"], cwd=ROOT, capture_output=True, text=True)
    return res.stdout if res.returncode == 0 else (ROOT / rel).read_text()


def yaml_files():
    for p in ROOT.rglob("*.y*ml"):
        if not {".git", ".venv", "node_modules"} & set(p.parts):
            yield p


STEPS = sorted(p for p in ROOT.iterdir() if p.is_dir() and re.fullmatch(r"\d\d-[a-z0-9-]+", p.name))
APPLICATIONS = sorted(ROOT.glob("[0-9][0-9]-*/application.yaml"))
KUSTOMIZE_DIRS = ["06-demo-app/manifests", "07-alert-rules/manifests",
                  "08-jira-integration/manifests", "09-agent-access/manifests", "12-agent-operator/manifests"]


def test_steps_are_numbered_consecutively():
    assert [int(p.name[:2]) for p in STEPS] == list(range(len(STEPS)))


@pytest.mark.parametrize("step", STEPS, ids=lambda p: p.name)
def test_step_has_readme_and_executable_scripts(step):
    assert (step / "README.md").exists()
    for script in ("run.sh", "verify.sh"):
        if (step / script).exists():
            assert (step / script).stat().st_mode & 0o111, f"{step.name}/{script} not executable"


@pytest.mark.parametrize("app", APPLICATIONS, ids=lambda p: p.parent.name)
def test_application_paths_exist(app):
    spec = yaml.safe_load(app.read_text())["spec"]
    for src in spec.get("sources", [spec.get("source")]):
        if src.get("path"):
            assert (ROOT / src["path"] / "kustomization.yaml").exists(), src["path"]
        for vf in src.get("helm", {}).get("valueFiles", []):
            assert (ROOT / vf.replace("$values/", "")).exists(), vf


def test_agent_scope_matches_demo_app():
    """Agent default, CI guard and the shop Application must agree on the agent's write path."""
    shop = yaml.safe_load((ROOT / "06-demo-app/application.yaml").read_text())
    path = shop["spec"]["source"]["path"] + "/"
    config = (ROOT / "11-agent/ai_sre_agent/config.py").read_text()
    ci = (ROOT / ".github/workflows/pr-checks.yaml").read_text()
    assert f'"AGENT_ALLOWED_PATHS", "{path}"' in config
    assert f"^({path}|incidents/)" in ci


@pytest.mark.parametrize("path", list(yaml_files()), ids=lambda p: str(p.relative_to(ROOT)))
def test_yaml_parses(path):
    list(yaml.safe_load_all(path.read_text()))


@pytest.mark.parametrize("kdir", KUSTOMIZE_DIRS)
def test_kustomization_references_exist(kdir):
    k = yaml.safe_load((ROOT / kdir / "kustomization.yaml").read_text())
    for res in k.get("resources", []):
        assert (ROOT / kdir / res).exists(), res
    for gen in k.get("configMapGenerator", []):
        for f in gen.get("files", []):
            assert (ROOT / kdir / f.split("=")[-1]).exists(), f


@pytest.mark.parametrize("sid", [s for s, v in demo.SCENARIOS.items() if "edits" in v])
def test_scenario_applies_once_and_stays_valid(sid):
    files = {}
    for edit in demo.SCENARIOS[sid]["edits"]:
        text = files.get(edit["file"]) or baseline_text(edit["file"])
        assert text.count(edit["find"]) == 1, f"{sid}: find string must match exactly once in {edit['file']}"
        files[edit["file"]] = text.replace(edit["find"], edit["replace"])
    for f, text in files.items():
        docs = list(yaml.safe_load_all(text))
        assert docs and all(isinstance(d, dict) for d in docs)


def test_scenario_semantics():
    def mutate(sid):
        text = baseline_text(demo.DEPLOY)
        for e in demo.SCENARIOS[sid]["edits"]:
            if e["file"] == demo.DEPLOY:
                text = text.replace(e["find"], e["replace"])
        return yaml.safe_load(text)["spec"]["template"]["spec"]["containers"][0]

    assert mutate("01-oomkilled")["resources"]["limits"]["memory"] == "64Mi"
    assert mutate("01-oomkilled")["resources"]["requests"]["memory"] == "48Mi"
    assert mutate("02-bad-image-tag")["image"].endswith(":6.15.0-hotfix1")
    assert mutate("03-readiness-probe")["readinessProbe"]["httpGet"]["port"] == 8080
    assert mutate("05-cpu-request-typo")["resources"]["requests"]["cpu"] == "50"


def _quantity(q: str) -> float:
    units = {"m": 1e-3, "Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "K": 1e3, "M": 1e6, "G": 1e9}
    for suffix, factor in sorted(units.items(), key=lambda u: -len(u[0])):
        if str(q).endswith(suffix):
            return float(str(q)[: -len(suffix)]) * factor
    return float(q)


@pytest.mark.parametrize("sid", [None] + [s for s, v in demo.SCENARIOS.items() if "edits" in v])
def test_requests_never_exceed_limits(sid):
    """The API server rejects request > limit; such a scenario would never roll out."""
    text = baseline_text(demo.DEPLOY)
    for e in demo.SCENARIOS[sid]["edits"] if sid else []:
        if e["file"] == demo.DEPLOY:
            text = text.replace(e["find"], e["replace"])
    for c in yaml.safe_load(text)["spec"]["template"]["spec"]["containers"]:
        res = c.get("resources", {})
        for name, limit in res.get("limits", {}).items():
            request = res.get("requests", {}).get(name)
            if request is not None:
                assert _quantity(request) <= _quantity(limit), f"{sid}: {name} request {request} > limit {limit}"


def test_alert_rules_cover_every_scenario():
    rules = yaml.safe_load((ROOT / "07-alert-rules/manifests/alert-rules.yaml").read_text())
    titles = {r["title"] for g in rules["groups"] for r in g["rules"]}
    for sid, s in demo.SCENARIOS.items():
        assert s["alert"] in titles, f"{sid} expects alert {s['alert']}"
    for g in rules["groups"]:
        for r in g["rules"]:
            assert r["labels"]["ai_triage"] == "true"
            assert "workload" in r["data"][0]["model"]["expr"]
            # Grafana expands $VARS outside the query model in provisioning files
            assert "$" not in r["annotations"]["summary"] + r["annotations"]["description"]


def test_repo_url_consistent():
    """Placeholder or configured, every manifest must point at the same repo URL."""
    urls = {}
    for p in yaml_files():
        for url in re.findall(r"https://github\.com/[^\s]+\.git", p.read_text()):
            urls.setdefault(url, []).append(str(p.relative_to(ROOT)))
    assert len(urls) == 1, urls
    files = next(iter(urls.values()))
    assert {str(a.relative_to(ROOT)) for a in APPLICATIONS} <= set(files)
    assert "06-demo-app/appproject.yaml" in files
