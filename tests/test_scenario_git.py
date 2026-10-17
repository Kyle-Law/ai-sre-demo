"""Exercise scenarios/demo.py inject/reset against a throwaway clone + bare remote."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git not installed")


def sh(*cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True).stdout


@pytest.fixture()
def repo(tmp_path):
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    sh("git", "init", "--bare", "-q", "-b", "main", str(remote), cwd=tmp_path)
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.db"))
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "demo@example.com"],
                 ["config", "user.name", "Demo Operator"], ["add", "-A"], ["commit", "-qm", "baseline"],
                 ["remote", "add", "origin", str(remote)], ["push", "-q", "origin", "main"]):
        sh("git", *args, cwd=work)
    sh("git", "branch", "--set-upstream-to=origin/main", cwd=work)
    return work, remote


def demo(work, *args):
    return subprocess.run(["python3", "scenarios/demo.py", *args], cwd=work, text=True, capture_output=True)


@pytest.mark.parametrize("sid", ["01-oomkilled", "02-bad-image-tag", "03-readiness-probe",
                                 "04-configmap-key", "05-cpu-request-typo"])
def test_inject_then_reset_roundtrip(repo, sid):
    work, remote = repo
    assert demo(work, "baseline").returncode == 0
    before = (work / "apps/shop/deployment.yaml").read_text() + (work / "apps/shop/configmap.yaml").read_text()

    r = demo(work, "inject", sid)
    assert r.returncode == 0, r.stderr
    log = sh("git", "--git-dir", str(remote), "log", "--oneline", "-1", "main", cwd=work)
    assert "reset" not in log  # the realistic bad commit reached the remote

    # A second scenario cannot be stacked on top of an active one... unless it touches other lines
    r2 = demo(work, "inject", sid)
    assert r2.returncode != 0 and "reset" in (r2.stdout + r2.stderr)

    r = demo(work, "reset")
    assert r.returncode == 0, r.stderr
    after = (work / "apps/shop/deployment.yaml").read_text() + (work / "apps/shop/configmap.yaml").read_text()
    assert after == before
    assert "reset apps/shop" in sh("git", "--git-dir", str(remote), "log", "--oneline", "-1", "main", cwd=work)


def test_dry_run_changes_nothing(repo):
    work, _ = repo
    demo(work, "baseline")
    r = demo(work, "--dry-run", "inject", "01-oomkilled")
    assert r.returncode == 0 and "64Mi" in r.stdout
    assert sh("git", "status", "--porcelain", cwd=work) == ""
