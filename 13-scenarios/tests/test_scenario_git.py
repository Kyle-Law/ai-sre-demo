"""Exercise 13-scenarios/demo.py inject/reset against a throwaway clone + bare remote."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git not installed")


def sh(*cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True).stdout


@pytest.fixture()
def repo(tmp_path):
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    sh("git", "init", "--bare", "-q", "-b", "main", str(remote), cwd=tmp_path)
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", ".pytest_cache", "*.db", ".venv", ".agent",
        "demo.env", "agent.env", "*.pem", "*.kubeconfig", ".demo-state.json"))
    # Start from the healthy app even if a scenario is injected in the real checkout.
    for rel in ("06-demo-app/manifests/deployment.yaml", "06-demo-app/manifests/configmap.yaml"):
        res = subprocess.run(["git", "show", f"demo-baseline:{rel}"], cwd=ROOT, capture_output=True, text=True)
        if res.returncode == 0:
            (work / rel).write_text(res.stdout)
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "demo@example.com"],
                 ["config", "user.name", "Demo Operator"], ["add", "-A"], ["commit", "-qm", "baseline"],
                 ["remote", "add", "origin", str(remote)], ["push", "-q", "origin", "main"]):
        sh("git", *args, cwd=work)
    sh("git", "branch", "--set-upstream-to=origin/main", cwd=work)
    return work, remote


def demo(work, *args):
    return subprocess.run(["python3", "13-scenarios/demo.py", *args], cwd=work, text=True, capture_output=True)


@pytest.mark.parametrize("sid", ["01-oomkilled", "02-bad-image-tag", "03-readiness-probe",
                                 "04-configmap-key", "05-cpu-request-typo"])
def test_inject_then_reset_roundtrip(repo, sid):
    work, remote = repo
    assert demo(work, "baseline").returncode == 0
    before = (work / "06-demo-app/manifests/deployment.yaml").read_text() + (work / "06-demo-app/manifests/configmap.yaml").read_text()

    r = demo(work, "inject", sid)
    assert r.returncode == 0, r.stderr
    log = sh("git", "--git-dir", str(remote), "log", "--oneline", "-1", "main", cwd=work)
    assert "reset" not in log  # the realistic bad commit reached the remote

    # A second scenario cannot be stacked on top of an active one... unless it touches other lines
    r2 = demo(work, "inject", sid)
    assert r2.returncode != 0 and "reset" in (r2.stdout + r2.stderr)

    r = demo(work, "reset")
    assert r.returncode == 0, r.stderr
    after = (work / "06-demo-app/manifests/deployment.yaml").read_text() + (work / "06-demo-app/manifests/configmap.yaml").read_text()
    assert after == before
    assert "reset 06-demo-app/manifests" in sh("git", "--git-dir", str(remote), "log", "--oneline", "-1", "main", cwd=work)


def test_dry_run_changes_nothing(repo):
    work, _ = repo
    demo(work, "baseline")
    r = demo(work, "--dry-run", "inject", "01-oomkilled")
    assert r.returncode == 0 and "64Mi" in r.stdout
    assert sh("git", "status", "--porcelain", cwd=work) == ""


def test_merged_agent_pr_is_pulled_before_reset(repo, tmp_path):
    """The agent's fix is merged on GitHub; reset must build on it, not on a stale local main."""
    work, remote = repo
    demo(work, "baseline")
    assert demo(work, "inject", "02-bad-image-tag").returncode == 0
    other = tmp_path / "github-merge"                      # someone merges the agent's PR remotely
    sh("git", "clone", "-q", str(remote), str(other), cwd=tmp_path)
    dep = other / "06-demo-app/manifests/deployment.yaml"
    dep.write_text(dep.read_text().replace(":6.15.0-hotfix1", ":6.15.0"))
    sh("git", "-c", "user.email=a@b", "-c", "user.name=agent", "commit", "-qam", "agent fix", cwd=other)
    sh("git", "push", "-q", "origin", "main", cwd=other)

    r = demo(work, "reset")
    assert r.returncode == 0, r.stderr                    # pulled the merge, then nothing left to reset
    assert "already matches" in r.stdout


def test_diverged_main_stops_with_instructions(repo, tmp_path):
    work, remote = repo
    demo(work, "baseline")
    other = tmp_path / "elsewhere"
    sh("git", "clone", "-q", str(remote), str(other), cwd=tmp_path)
    (other / "NOTES.md").write_text("remote change\n")
    sh("git", "add", "NOTES.md", cwd=other)
    sh("git", "-c", "user.email=a@b", "-c", "user.name=x", "commit", "-qm", "remote", cwd=other)
    sh("git", "push", "-q", "origin", "main", cwd=other)
    (work / "LOCAL.md").write_text("unpushed local change\n")
    sh("git", "add", "LOCAL.md", cwd=work)
    sh("git", "commit", "-qm", "local", cwd=work)

    r = demo(work, "inject", "01-oomkilled")
    assert r.returncode != 0 and "git pull --rebase origin main" in r.stderr
    assert "64Mi" not in (work / "06-demo-app/manifests/deployment.yaml").read_text()
