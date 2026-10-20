"""One call for a Text AI task (ADR 0046, Architecture 7.3, System Design 7.3).

`run_task` reads the active prompt version from its file, fits reference text to the
task's budget and only then calls the gateway, so callers cannot forget to trim and never
pass a literal version. Learner text is never trimmed: an over-long one is refused here,
before admission, so it spends no quota. The gateway's admission is unchanged and still
refuses anything over budget, whoever calls it.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from listenup.ai.gateway import AIGateway
from listenup.ai.policy import CallContext
from listenup.ai.ports import TextGeneration
from listenup.ai.prompt_files import PROMPTS_DIR, load_prompt, load_task
from listenup.ai.prompt_render import fit
from listenup.ai.tasks import TASK_MODELS


@dataclass(frozen=True)
class TaskOutput[T: BaseModel]:
    result: TextGeneration[T]
    trimmed: tuple[str, ...]  # input fields shortened to fit, for the caller to record


async def run_task[T: BaseModel](
    gateway: AIGateway,
    name: str,
    input: Mapping[str, Any],
    output_schema: type[T],
    *,
    context: CallContext | None = None,
    root: Path = PROMPTS_DIR,
) -> TaskOutput[T]:
    """Raises `InputTooLarge` when even trimmed reference text leaves no room, and
    `AIUnavailable` when no provider produced a valid result."""
    if TASK_MODELS.get(name) is not output_schema:
        raise ValueError("output schema does not belong to the task")
    task = load_task(name, root=root)
    spec = load_prompt(name, task.version, root=root)
    fitted = fit(spec, input, gateway.text_input_budget(name))
    result = await gateway.generate(task, fitted.input, output_schema, context=context)
    return TaskOutput(result, fitted.trimmed)
