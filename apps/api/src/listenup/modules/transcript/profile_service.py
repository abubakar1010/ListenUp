"""Queue original evidence after transcription; no mode depends on its readiness."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.ai.gateway import get_gateway
from listenup.ai.ports import Role
from listenup.ai.providers.parselmouth_acoustics import SETTINGS, VERSION
from listenup.modules.content import service as content
from listenup.modules.practice import service as practice
from listenup.modules.transcript import profile_repository as profiles
from listenup.modules.transcript import repository
from listenup.modules.transcript.domain.spans import missing_spans, padded_span
from listenup.modules.transcript.profile_packing import fingerprint
from listenup.platform.errors import ProblemError
from listenup.platform.jobs import enqueue

PROFILE = "transcript.profile_span"


def recipe() -> dict[str, Any]:
    gateway = get_gateway()
    return {
        "format_version": 1,
        "alignment": gateway.deployment_provenance(Role.ALIGNMENT).model_dump(),
        "alignment_options": gateway.entry(Role.ALIGNMENT).options,
        "acoustics": {
            "provider": "parselmouth",
            "model": "praat-pitch-intensity",
            "version": VERSION,
            "settings": dict(SETTINGS),
        },
        "audio": {"sample_rate": 16000, "channels": 1, "format": "pcm_s16le"},
    }


async def queue_profile(db: AsyncSession, learner: uuid.UUID, session_id: uuid.UUID) -> None:
    """Worker hook. Authorized original transcript spans only; never learner overlays."""
    session = await practice.get_session(db, session_id)
    if session.user_id != learner:
        raise ProblemError(404, "session_not_found", "There is no such session.")
    source = await content.transcription_source(db, learner, session.content_id)
    span = padded_span(session.passage.start_ms, session.passage.end_ms, source.duration_ms)
    await profiles.lock(db, source.media_id)
    rows = await repository.overlapping(db, source.media_id, span)
    if missing_spans(span, [row.bounds for row in rows]):
        raise ProblemError(409, "transcript_not_ready", "The passage transcript is not ready yet.")
    key = fingerprint(recipe())
    await profiles.subscribe(db, session_id, learner, source.media_id, span, key)
    for row in rows:
        profile = await profiles.ensure(db, row.id, key)
        if profile.status != "ready":
            job_key = f"profile:{row.id}:{key}"
            await enqueue(
                db,
                PROFILE,
                unique_key=job_key,
                lock=job_key,
                transcript_id=str(row.id),
                fingerprint=key,
            )
    await profiles.settle(db, source.media_id)
