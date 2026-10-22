"""Prefetch passage key points on the AI lane (#67, FR-BL-6, NFR-AI-4/5)."""

import uuid

from sqlalchemy.exc import IntegrityError

from listenup.ai import prompt_files, text_tasks
from listenup.ai.gateway import get_gateway
from listenup.ai.tasks import EXTRACT_KEY_POINTS, KeyPoints
from listenup.modules.grading import repository, service
from listenup.modules.transcript import service as transcript
from listenup.platform.jobs import JobDeps, Lane, PermanentError, job


@job(Lane.AI, service.EXTRACT_KEY_POINTS)
async def extract_key_points(deps: JobDeps, media_id: str, start_ms: int, end_ms: int) -> None:
    """Procrastinate's passage lock is held from cache lookup through commit.

    Invalid output/unavailable providers propagate to the lane's bounded retries.
    No partial reference is stored, and neither a retry nor exhaustion blocks Blind.
    """
    media = uuid.UUID(media_id)
    if not 0 <= start_ms < end_ms:
        raise PermanentError("Invalid passage bounds")
    span = (start_ms, end_ms)
    task = prompt_files.load_task(EXTRACT_KEY_POINTS, root=prompt_files.PROMPTS_DIR)
    async with deps.database.transaction() as db:
        if await repository.find(db, media, span, task.version) is not None:
            return
        passage = await transcript.key_points_reference(db, media, span)
    if passage is None:  # media was deleted; nothing may recreate it
        return
    if not passage.strip():
        raise PermanentError("The passage contains no transcribed words")
    result = (
        await text_tasks.run_task(
            get_gateway(),
            EXTRACT_KEY_POINTS,
            {"transcript": passage},
            KeyPoints,
        )
    ).result
    points = [
        dict(id=f"kp{i}", **point.model_dump())
        for i, point in enumerate(result.value.key_points, 1)
    ]
    try:
        async with deps.database.transaction() as db:
            await repository.store(
                db, media, span, result.prompt_version, points, result.provenance.model_dump()
            )
    except IntegrityError as error:
        # The cache has exactly one FK: media. A deletion during inference wins.
        if getattr(error.orig, "sqlstate", None) != "23503":
            raise


transcript.on_passage_ready(service.on_transcript_ready)
