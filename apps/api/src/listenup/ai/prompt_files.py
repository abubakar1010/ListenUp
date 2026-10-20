"""Versioned prompt files: `ai/prompts/<task>/<version>.md` and `<task>/schema.json`
(Architecture 7.3, NFR-AI-4, NFR-AI-5).

A prompt file starts with YAML front matter (task, version, status, input fields) and its
body is the system prompt. The version recorded with a stored result is the `version` in
the active file, read here, so editing the file changes what is recorded and no caller
hardcodes one. Exactly one version per task is `active`; retired versions stay so old
results can be told apart from new ones. `manifest.json` locks every released file's hash:
changing one needs a visible manifest edit, and a behaviour change needs a new version.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from listenup.ai.ports import TextTask
from listenup.ai.tasks import TASK_MODELS

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
MANIFEST = "manifest.json"
DELIMITER = "{{DELIM}}"  # replaced by a per-call data-block marker (prompt_render.py)

_TASK = re.compile(r"[a-z][a-z0-9_]{0,63}")
_VERSION = re.compile(r"[a-z0-9][a-z0-9_.-]{0,31}")


class PromptError(ValueError):
    """A prompt file, its schema or its name is invalid."""


class InputField(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    # Reference text that may be shortened to fit the budget. Learner text is never
    # trimmable: it is refused when too long instead (ADR 0046).
    trim: bool = False


class _FrontMatter(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task: str
    version: str
    status: Literal["active", "retired"]
    input_fields: tuple[InputField, ...] = Field(min_length=1)


class PromptSpec(_FrontMatter):
    body: str
    output_schema: dict[str, Any]

    @property
    def field_names(self) -> frozenset[str]:
        return frozenset(f.name for f in self.input_fields)


def _check_names(task: str, version: str | None) -> None:
    if not _TASK.fullmatch(task) or task not in TASK_MODELS:
        raise PromptError("unknown task")
    if version is not None and not _VERSION.fullmatch(version):
        raise PromptError("invalid prompt version")


def _parse(path: Path) -> tuple[_FrontMatter, str]:
    text = path.read_text(encoding="utf-8")
    head, sep, body = text.removeprefix("---\n").partition("\n---\n")
    if not text.startswith("---\n") or not sep:
        raise PromptError(f"{path.name}: missing front matter")
    try:
        return _FrontMatter.model_validate(yaml.safe_load(head)), body.strip()
    except (yaml.YAMLError, ValidationError) as error:
        raise PromptError(f"{path.name}: invalid front matter") from error


def load_prompt(task: str, version: str | None = None, *, root: Path = PROMPTS_DIR) -> PromptSpec:
    """The prompt `version` of `task`, or its active version when none is given."""
    _check_names(task, version)
    folder = root / task
    files = {}
    for path in sorted(folder.glob("*.md")):
        front, body = _parse(path)
        if front.task != task or front.version != path.stem:
            raise PromptError(f"{path.name}: task or version does not match the file")
        files[front.version] = (front, body)
    active = [v for v, (front, _) in files.items() if front.status == "active"]
    if len(active) != 1:
        raise PromptError(f"{task}: exactly one active version is required")
    wanted = version or active[0]
    if wanted not in files:
        raise PromptError(f"{task}: no prompt version {wanted}")
    try:
        schema = json.loads((folder / "schema.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PromptError(f"{task}: unreadable schema.json") from error
    front, body = files[wanted]
    return PromptSpec(**front.model_dump(), body=body, output_schema=schema)


def load_task(task: str, *, root: Path = PROMPTS_DIR) -> TextTask:
    """What callers pass to the gateway: the task name and the version written in the file."""
    spec = load_prompt(task, root=root)
    return TextTask(spec.task, spec.version)


def manifest(root: Path = PROMPTS_DIR) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.glob("*/*"))
        if path.is_file()
    }


def write_manifest(root: Path = PROMPTS_DIR) -> None:
    """Run after an intended prompt or schema edit:
    `uv run python -c "from listenup.ai.prompt_files import write_manifest; write_manifest()"`."""
    (root / MANIFEST).write_text(json.dumps(manifest(root), indent=2) + "\n", encoding="utf-8")
