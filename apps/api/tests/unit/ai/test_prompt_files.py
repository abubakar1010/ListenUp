"""Versioned prompt files (Architecture 7.3, NFR-AI-4, NFR-AI-5): the version recorded with
a result is the one written in the prompt file, and released files cannot change silently."""

import hashlib
import json
from pathlib import Path

import pytest

from listenup.ai import prompt_files
from listenup.ai.prompt_files import PromptError, load_prompt, load_task
from listenup.ai.tasks import TASK_INPUTS, TASK_MODELS

FRONT = """---
task: {task}
version: {version}
status: {status}
input_fields:
  - {{name: gist, trim: false}}
  - {{name: transcript, trim: true}}
---
Grade the gist. Data is between {{{{DELIM}}}} markers.
"""


def write_prompt(root: Path, version: str, *, task="grade_gist", status="active", name=None):
    folder = root / task
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "schema.json").write_text("{}")
    (folder / f"{name or version}.md").write_text(
        FRONT.format(task=task, version=version, status=status)
    )


def test_prompt_version_is_read_from_file(tmp_path):
    write_prompt(tmp_path, "v1")
    assert load_task("grade_gist", root=tmp_path).version == "v1"
    (tmp_path / "grade_gist" / "v1.md").unlink()
    write_prompt(tmp_path, "v2")
    task = load_task("grade_gist", root=tmp_path)
    assert (task.name, task.version) == ("grade_gist", "v2")


def test_version_is_the_one_inside_the_file_not_the_name(tmp_path):
    write_prompt(tmp_path, "v2", name="v1")
    with pytest.raises(PromptError, match="does not match"):
        load_task("grade_gist", root=tmp_path)


def test_exactly_one_active_version_per_task(tmp_path):
    write_prompt(tmp_path, "v1")
    write_prompt(tmp_path, "v2")
    with pytest.raises(PromptError, match="exactly one active"):
        load_task("grade_gist", root=tmp_path)
    (tmp_path / "grade_gist" / "v2.md").write_text(
        FRONT.format(task="grade_gist", version="v2", status="retired")
    )
    assert load_task("grade_gist", root=tmp_path).version == "v1"
    (tmp_path / "grade_gist" / "v1.md").unlink()
    with pytest.raises(PromptError, match="exactly one active"):
        load_task("grade_gist", root=tmp_path)


def test_retired_version_can_be_loaded_by_version(tmp_path):
    write_prompt(tmp_path, "v1", status="retired")
    write_prompt(tmp_path, "v2")
    assert load_prompt("grade_gist", "v1", root=tmp_path).status == "retired"


@pytest.mark.parametrize("task", ["../grade_gist", "Grade", "", "a/b", "unknown_task"])
def test_unsafe_or_unknown_task_names_are_refused(tmp_path, task):
    write_prompt(tmp_path, "v1")
    with pytest.raises(PromptError):
        load_prompt(task, root=tmp_path)


@pytest.mark.parametrize("version", ["../v1", "v1/x", "", "V 1"])
def test_unsafe_versions_are_refused(tmp_path, version):
    write_prompt(tmp_path, "v1")
    with pytest.raises(PromptError):
        load_prompt("grade_gist", version, root=tmp_path)


def test_unlisted_front_matter_keys_are_refused(tmp_path):
    write_prompt(tmp_path, "v1")
    path = tmp_path / "grade_gist" / "v1.md"
    path.write_text(path.read_text().replace("status: active", "status: active\nextra: 1"))
    with pytest.raises(PromptError):
        load_prompt("grade_gist", "v1", root=tmp_path)


def test_trimmable_fields_are_listed_in_the_file(tmp_path):
    write_prompt(tmp_path, "v1")
    spec = load_prompt("grade_gist", root=tmp_path)
    assert [f.name for f in spec.input_fields if f.trim] == ["transcript"]


@pytest.mark.parametrize("task", sorted(TASK_MODELS))
def test_shipped_task_has_one_active_prompt_and_matching_schema(task):
    spec = load_prompt(task)
    assert spec.status == "active"
    assert spec.output_schema == TASK_MODELS[task].model_json_schema()
    assert "{{DELIM}}" in spec.body
    # The prompt file lists exactly the fields of the task's input model.
    assert spec.field_names == set(TASK_INPUTS[task].model_fields)


def test_every_task_model_has_a_prompt_folder_and_the_other_way_round():
    folders = {p.name for p in prompt_files.PROMPTS_DIR.iterdir() if p.is_dir()}
    assert folders == set(TASK_MODELS)


def test_released_prompt_hash_lock():
    """A released prompt or schema changes only together with `manifest.json`, so the edit
    shows in review; a behaviour change needs a new version (NFR-AI-5)."""
    locked = json.loads((prompt_files.PROMPTS_DIR / "manifest.json").read_text())
    actual = {
        str(path.relative_to(prompt_files.PROMPTS_DIR)): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(prompt_files.PROMPTS_DIR.glob("*/*"))
    }
    assert actual == locked
    assert prompt_files.manifest() == locked


def test_a_file_without_front_matter_is_refused(tmp_path):
    write_prompt(tmp_path, "v1")
    (tmp_path / "grade_gist" / "v1.md").write_text("Just text, no front matter.")
    with pytest.raises(PromptError, match="front matter"):
        load_prompt("grade_gist", root=tmp_path)


def test_a_version_that_does_not_exist_is_refused(tmp_path):
    write_prompt(tmp_path, "v1")
    with pytest.raises(PromptError, match="no prompt version"):
        load_prompt("grade_gist", "v2", root=tmp_path)


def test_missing_schema_is_refused(tmp_path):
    write_prompt(tmp_path, "v1")
    (tmp_path / "grade_gist" / "schema.json").unlink()
    with pytest.raises(PromptError, match="schema"):
        load_prompt("grade_gist", root=tmp_path)


def test_write_manifest_records_the_current_hashes(tmp_path):
    write_prompt(tmp_path, "v1")
    prompt_files.write_manifest(tmp_path)
    assert json.loads((tmp_path / "manifest.json").read_text()) == prompt_files.manifest(tmp_path)
    assert set(prompt_files.manifest(tmp_path)) == {"grade_gist/schema.json", "grade_gist/v1.md"}
