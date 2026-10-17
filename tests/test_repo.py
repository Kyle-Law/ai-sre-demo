"""Repo-level checks: manifests parse, kustomize resource lists resolve, every scenario
applies cleanly to the baseline and produces valid YAML, and placeholders are consistent."""

import importlib.util
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("demo", ROOT / "scenarios/demo.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


def yaml_files():
    for p in ROOT.rglob("*.y*ml"):
        if ".git" not in p.parts and "node_modules" not in p.parts:
            yield p


@pytest.mark.parametrize("path", list(yaml_files()), ids=lambda p: str(p.relative_to(ROOT)))
def test_yaml_parses(path):
    list(yaml.safe_load_all(path.read_text()))


@pytest.mark.parametrize("kdir", ["apps/shop", "platform/ai-sre", "platform/monitoring-config"])
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
        text = files.get(edit["file"]) or (ROOT / edit["file"]).read_text()
        assert text.count(edit["find"]) == 1, f"{sid}: find string must match exactly once in {edit['file']}"
        files[edit["file"]] = text.replace(edit["find"], edit["replace"])
    for f, text in files.items():
        docs = list(yaml.safe_load_all(text))
        assert docs and all(isinstance(d, dict) for d in docs)


def test_scenario_semantics():
    def mutate(sid):
        text = (ROOT / demo.DEPLOY).read_text()
        for e in demo.SCENARIOS[sid]["edits"]:
            if e["file"] == demo.DEPLOY:
                text = text.replace(e["find"], e["replace"])
        return yaml.safe_load(text)["spec"]["template"]["spec"]["containers"][0]

    assert mutate("01-oomkilled")["resources"]["limits"]["memory"] == "64Mi"
    assert mutate("02-bad-image-tag")["image"].endswith(":6.15.0-hotfix1")
    assert mutate("03-readiness-probe")["readinessProbe"]["httpGet"]["port"] == 8080
    assert mutate("05-cpu-request-typo")["resources"]["requests"]["cpu"] == "50"


def test_alert_rules_cover_every_scenario():
    rules = yaml.safe_load((ROOT / "platform/monitoring-config/alert-rules.yaml").read_text())
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
    for p in ROOT.rglob("*.yaml"):
        for url in re.findall(r"https://github\.com/[^\s]+\.git", p.read_text()):
            urls.setdefault(url, []).append(str(p.relative_to(ROOT)))
    assert len(urls) == 1, urls
    files = next(iter(urls.values()))
    assert "bootstrap/root-app.yaml" in files and "argocd/apps/shop.yaml" in files
