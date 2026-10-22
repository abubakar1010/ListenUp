"""Exercise the actual change-selection shell script against temporary Git history."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[5]


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


@pytest.fixture
def history(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    package = tmp_path / "apps/api/src/listenup/ai/evals"
    package.mkdir(parents=True)
    for directory in [package, package.parent, package.parent.parent]:
        (directory / "__init__.py").touch()
    shutil.copyfile(ROOT / "apps/api/src/listenup/ai/evals/paths.py", package / "paths.py")
    (tmp_path / "readme").write_text("initial")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "initial")
    base = git(tmp_path, "rev-parse", "HEAD")
    git(tmp_path, "update-ref", "refs/remotes/origin/main", base)
    return tmp_path, base


def selection(root, base, event="push"):
    return subprocess.check_output(
        ["bash", str(ROOT / ".github/scripts/ai-evals-changes.sh")],
        cwd=root,
        text=True,
        env={
            **os.environ,
            "BASE_SHA": base,
            "HEAD_SHA": "HEAD",
            "DEFAULT_BRANCH": "main",
            "EVENT_NAME": event,
        },
    ).strip()


def test_workflow_detects_prompt_add_delete_and_rename(history):
    root, base = history
    prompt = root / "apps/api/src/listenup/ai/prompts/task/v1.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("example")
    git(root, "add", ".")
    git(root, "commit", "-m", "add prompt")
    assert selection(root, base) == "true"
    added = git(root, "rev-parse", "HEAD")
    prompt.rename(root / "moved.txt")
    git(root, "add", ".")
    git(root, "commit", "-m", "move out of prompts")
    assert selection(root, added) == "true"


def test_new_branch_push_compares_against_main(history):
    root, _ = history
    (root / "readme").write_text("edited")
    git(root, "add", ".")
    git(root, "commit", "-m", "unrelated")
    assert selection(root, "0" * 40) == "false"


def test_pr_ignores_ai_changes_only_on_the_base_branch(history):
    root, base = history
    path = root / "apps/api/src/listenup/ai/providers/example.py"
    path.parent.mkdir(parents=True)
    path.write_text("# base branch only")
    git(root, "add", ".")
    git(root, "commit", "-m", "change provider on main")
    base_tip = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "-b", "feature", base)
    (root / "readme").write_text("unrelated PR")
    git(root, "add", ".")
    git(root, "commit", "-m", "unrelated feature")
    assert selection(root, base_tip, event="pull_request") == "false"


def test_ci_smoke_is_conditional_offline_and_uploads_failure_reports():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["ai-evals-smoke"]
    assert job["needs"] == "ai-evals-changes"
    assert job["if"] == "needs.ai-evals-changes.outputs.smoke == 'true'"
    command = next(
        s["run"]
        for s in job["steps"]
        if s.get("name") == "Run both synthetic subsets through the report gate"
    )
    assert "--offline --smoke" in command
    assert "--ai-config src/listenup/ai/ai.fake.yaml" in command
    assert "for suite in gist shadow" in command
    assert 'exit "$result"' in command
    artifact = job["steps"][-1]
    assert artifact["uses"] == "actions/upload-artifact@v4"
    assert artifact["if"] == "always()"
    assert artifact["with"]["if-no-files-found"] == "error"


def test_change_detection_failure_fails_ci_step(tmp_path):
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    command = workflow["jobs"]["ai-evals-changes"]["steps"][-1]["run"]
    scripts = tmp_path / ".github/scripts"
    scripts.mkdir(parents=True)
    (scripts / "ai-evals-changes.sh").write_text("exit 7\n")
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", command],
        cwd=tmp_path,
        env={**os.environ, "GITHUB_OUTPUT": str(tmp_path / "output")},
    )
    assert result.returncode == 7
