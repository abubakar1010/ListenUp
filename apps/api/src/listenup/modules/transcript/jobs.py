"""Passage-only intake transcription via the configured AI gateway (#45)."""

import asyncio
import tempfile
import uuid
from pathlib import Path

from listenup.ai.gateway import get_gateway
from listenup.modules.content import service as content
from listenup.modules.identity import service as identity
from listenup.modules.practice import service as practice
from listenup.modules.transcript import repository
from listenup.modules.transcript import service as transcript
from listenup.modules.transcript.domain.spans import Span, missing_spans, padded_span
from listenup.modules.transcript.packing import pack
from listenup.platform.config import get_settings
from listenup.platform.events import EventType, publish
from listenup.platform.jobs import JobDeps, Lane, PermanentError, job
from listenup.platform.storage import get_storage

TRANSCRIBE = "transcript.transcribe_passage"


async def extract(source: Path, target: Path, span: Span) -> None:
    """Decode a bounded window to 16 kHz mono PCM; VAD stays in the adapter."""
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-ss",
        str(span[0] / 1000),
        "-i",
        str(source),
        "-t",
        str((span[1] - span[0]) / 1000),
        "-vn",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(target),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        if await process.wait() != 0:
            raise PermanentError("Audio window could not be decoded")
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def _context(
    deps: JobDeps, identifier: uuid.UUID, learner: uuid.UUID
) -> tuple[practice.PracticeSession, content.TranscriptionSource] | None:
    from listenup.platform.errors import ProblemError

    async with deps.database.transaction(learner) as db:
        if not await identity.account_is_active(db, learner):
            return None
        try:
            session = await practice.get_session(db, identifier)
            if session.user_id != learner:
                raise PermanentError("Session does not belong to job owner")
            source = await content.transcription_source(db, learner, session.content_id)
        except ProblemError as error:
            if error.status == 404:
                return None
            raise
    return session, source


async def _give_up(deps: JobDeps, session_id: str, user_id: str) -> None:
    learner, identifier = uuid.UUID(user_id), uuid.UUID(session_id)
    context = await _context(deps, identifier, learner)
    if context is None:
        return
    session, source = context
    span = padded_span(session.passage.start_ms, session.passage.end_ms, source.duration_ms)
    async with (
        repository.media_lock(deps.database, source.media_id),
        deps.database.transaction() as db,
    ):
        cached = await repository.overlapping(db, source.media_id, span)
        gaps = missing_spans(span, [r.bounds for r in cached])
        await repository.mark_failed(db, source.media_id, gaps)
        if gaps:
            await publish(db, learner, EventType.TRANSCRIPT_FAILED, identifier)


@job(Lane.INTAKE, TRANSCRIBE, on_give_up=_give_up)
async def transcribe_passage(deps: JobDeps, session_id: str, user_id: str) -> None:
    try:
        await _transcribe(deps, uuid.UUID(session_id), uuid.UUID(user_id))
    except PermanentError:
        # run_handler leaves permanent failures to the handler (ADR 0029).
        await _give_up(deps, session_id, user_id)
        raise


async def _transcribe(deps: JobDeps, identifier: uuid.UUID, learner: uuid.UUID) -> None:
    context = await _context(deps, identifier, learner)
    if context is None:
        return
    session, source = context
    span = padded_span(session.passage.start_ms, session.passage.end_ms, source.duration_ms)
    async with repository.media_lock(deps.database, source.media_id):
        async with deps.database.transaction() as db:
            cached = await repository.overlapping(db, source.media_id, span)
        gaps = missing_spans(span, [row.bounds for row in cached])
        if gaps:
            with tempfile.TemporaryDirectory(
                prefix="transcript-", dir=get_settings().media_scratch_dir
            ) as scratch:
                playback, audio = Path(scratch) / "playback.mp4", Path(scratch) / "window.wav"
                if await get_storage().download(source.playback_key, playback) is None:
                    raise PermanentError("Playback audio is missing")
                for gap in gaps:
                    await extract(playback, audio, gap)
                    result = await get_gateway().transcribe(audio, language="en")
                    try:
                        packed = pack(result, gap)
                    except ValueError as error:
                        raise PermanentError("Invalid provider word timings") from error
                    # Account/content deletion during inference must not resurrect data.
                    if await _context(deps, identifier, learner) is None:
                        return
                    async with deps.database.transaction() as db:
                        await repository.store(db, source.media_id, gap, packed)
        async with deps.database.transaction() as db:
            if await identity.account_is_active(db, learner):
                await publish(db, learner, EventType.TRANSCRIPT_READY, identifier)
                # Modes waiting for the words (Dictation scoring, #54) continue now.
                await transcript.announce_ready(db, learner, identifier)
