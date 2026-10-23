"""Prefetch passage key points on the AI lane (#67, FR-BL-6, NFR-AI-4/5)."""

import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError

from listenup.ai import prompt_files, text_tasks
from listenup.ai.gateway import get_gateway
from listenup.ai.tasks import EXTRACT_KEY_POINTS, GRADE_GIST, GistGrade, KeyPoints
from listenup.modules.blind import service as blind
from listenup.modules.grading import repository, service
from listenup.modules.grading.domain.feedback import validate_feedback
from listenup.modules.grading.domain.scoring import Rubric
from listenup.modules.identity import service as identity
from listenup.modules.transcript import service as transcript
from listenup.platform.errors import ProblemError
from listenup.platform.events import EventType, publish
from listenup.platform.jobs import JobDeps, Lane, PermanentError, job
from listenup.platform.telemetry import record_grading

GRADE_GIST_JOB = service.GRADE_GIST


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
    output = await text_tasks.run_task(
        get_gateway(),
        EXTRACT_KEY_POINTS,
        {"transcript": passage},
        KeyPoints,
    )
    result = output.result
    provenance = {**result.provenance.model_dump(), "trimmed_fields": list(output.trimmed)}
    points = [
        dict(id=f"kp{i}", **point.model_dump())
        for i, point in enumerate(result.value.key_points, 1)
    ]
    try:
        async with deps.database.transaction() as db:
            await repository.store(db, media, span, result.prompt_version, points, provenance)
    except IntegrityError as error:
        # The cache has exactly one FK: media. A deletion during inference wins.
        if getattr(error.orig, "sqlstate", None) != "23503":
            raise


transcript.on_passage_ready(service.on_transcript_ready)


@job(Lane.AI, GRADE_GIST_JOB)
async def grade_gist(deps: JobDeps, attempt_id: str, user_id: str) -> None:
    """Private inference, deterministic score and atomic ready event (FR-BL-6 to 14).

    Missing references and invalid replies retain the pending row and use the
    lane's existing bounded retries. Unavailable/retry UX belongs to #70.
    """
    learner, attempt = uuid.UUID(user_id), uuid.UUID(attempt_id)
    async with deps.database.transaction(learner) as db:
        if not await identity.account_is_active(db, learner):
            return
        row = await repository.grade(db, learner, attempt)
        if row is None or row.status != "pending":
            return
        try:
            source = await blind.gist_for_grading(db, learner, attempt)
        except ProblemError as error:
            if error.status == 404:
                return
            raise
        if source is None:
            return
        reference_version = prompt_files.load_task(
            EXTRACT_KEY_POINTS, root=prompt_files.PROMPTS_DIR
        ).version
        points = await repository.find(db, source.media_id, source.span, reference_version)
        if points is None:
            raise RuntimeError("Key points are not ready")
        passage = await transcript.key_points_reference(db, source.media_id, source.span)
        if passage is None:
            return
        if not passage.strip():
            raise PermanentError("The passage contains no transcribed words")
        input: dict[str, Any] = {
            "transcript": passage,
            "key_points": points.points,
            "gist": source.gist,
        }
        points_id = points.id

    output = await text_tasks.run_task(get_gateway(), GRADE_GIST, input, GistGrade)
    result, value = output.result, output.result.value
    validate_feedback(value.feedback)
    if not set(value.covered_points) <= {point["id"] for point in input["key_points"]}:
        raise ValueError("Unknown covered key point")
    rubric = Rubric.load(
        prompt_files.PROMPTS_DIR / GRADE_GIST / f"{result.prompt_version}.rubric.json"
    )
    scores = value.dimension_scores.model_dump()
    overall = rubric.score(scores)
    async with deps.database.transaction(learner) as db:
        if not await identity.account_is_active(db, learner):
            return
        saved = await repository.finish_grade(
            db,
            learner,
            attempt,
            {
                "key_points_id": points_id,
                "dimension_scores": scores,
                "overall": overall,
                "level": rubric.level(overall),
                "covered_points": list(value.covered_points),
                "wrong_claims": list(value.wrong_claims),
                "feedback": value.feedback,
                "rubric_version": rubric.version,
                "provider_info": {
                    **result.provenance.model_dump(),
                    "prompt_version": result.prompt_version,
                    "trimmed_fields": list(output.trimmed),
                },
            },
        )
        if saved:
            await publish(db, learner, EventType.GRADE_READY, attempt)
    if saved:
        record_grading("gist", True)
