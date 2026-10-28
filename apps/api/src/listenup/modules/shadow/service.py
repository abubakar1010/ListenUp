"""Shadow segment selection, playback rounds and private recordings (#77, #79, #81)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.practice import service as practice
from listenup.modules.review import service as review
from listenup.modules.shadow import repository, schemas
from listenup.modules.shadow.domain.segment import propose, validate
from listenup.modules.shadow.models import ShadowSegment
from listenup.modules.transcript import service as transcript
from listenup.platform.database import Database
from listenup.platform.errors import ProblemError
from listenup.platform.export import ExportPart, learner_rows
from listenup.platform.storage import Storage


def present(row: ShadowSegment) -> schemas.Segment:
    assert row.span.lower is not None and row.span.upper is not None
    return schemas.Segment(
        session_id=row.session_id,
        start_ms=row.span.lower,
        end_ms=row.span.upper,
        chosen_by=row.chosen_by,
        mark_count=row.mark_count,
        locked_at=row.locked_at,
    )


async def require_open_or_done(db: AsyncSession, session_id: uuid.UUID) -> practice.PracticeSession:
    """The session while Shadow is open or done; a skipped or unreached Shadow is refused.

    A done Shadow keeps its segment, rounds and recordings readable (SR-6, FR-SH-8).
    """
    session = await practice.require_reached(db, session_id, practice.Step.SHADOW)
    if not any(
        state.step is practice.Step.SHADOW and state.status is practice.StepStatus.DONE
        for state in session.plan.steps
    ):
        return await practice.require_step(db, session_id, practice.Step.SHADOW)
    return session


async def segment(
    db: AsyncSession, session_id: uuid.UUID, choice: schemas.SegmentChoice | None = None
) -> schemas.Segment:
    await practice.lock_session(db, session_id)
    session = await (
        require_open_or_done(db, session_id)
        if choice is None
        else practice.require_step(db, session_id, practice.Step.SHADOW)
    )
    row = await repository.get(db, session_id)
    if choice is None and row is not None:
        return present(row)
    if row is not None and row.locked_at is not None:
        raise ProblemError(409, "segment_locked", "The segment is fixed once round 1 starts.")
    p = session.passage
    marks = [m.at_ms for m in await review.list_marks(db, session_id)]
    if choice is None:
        start, end, count = propose(p.start_ms, p.end_ms, marks)
    else:
        start, end = choice.start_ms, choice.end_ms
        try:
            validate(p.start_ms, p.end_ms, start, end)
        except ValueError as error:
            raise ProblemError(
                422,
                "segment_span",
                "Choose 60 to 90 seconds, or the whole passage when it is under 60 seconds.",
            ) from error
        count = sum(start <= m < end for m in marks)
    return present(
        await repository.save(
            db,
            session_id,
            session.user_id,
            start,
            end,
            count,
            "system" if choice is None else "learner",
        )
    )


async def export_data(session: AsyncSession, learner: uuid.UUID) -> ExportPart:
    return ExportPart(
        tables=(
            await learner_rows(session, "practice.shadow_segments", learner, order_by="session_id"),
            await learner_rows(session, "practice.shadow_rounds", learner, order_by="created_at"),
        )
    )


async def round_state(
    db: AsyncSession, session_id: uuid.UUID, worker_database: Database, learner: uuid.UUID
) -> schemas.Rounds:
    selection = await segment(db, session_id)
    rows = await repository.rounds(db, session_id)
    summaries = [
        schemas.Round(
            id=r.id,
            round=r.round,
            transcript_shown=r.transcript_shown,
            playback_status=r.playback_status,
            recorded_at=r.recorded_at,
            recording_available=r.uploaded_at is not None,
            feedback="unavailable" if r.uploaded_at is not None else None,
        )
        for r in rows
    ]
    state = schemas.Rounds(
        segment=selection, current=summaries[-1] if summaries else None, rounds=summaries
    )
    if state.current is not None and state.current.round == 1:
        words = await transcript.read_passage(db, worker_database, learner, session_id)
        state.text = " ".join(
            word
            for word, at in zip(words.words, words.start_ms, strict=True)
            if selection.start_ms <= at < selection.end_ms
        )
    return state


async def change_round(
    db: AsyncSession, session_id: uuid.UUID, number: int, *, ended: bool = False
) -> None:
    await practice.lock_session(db, session_id)
    session = await practice.require_step(db, session_id, practice.Step.SHADOW)
    if number > 3:
        raise ProblemError(409, "round_limit", "Shadow has only three rounds.")
    await segment(db, session_id)
    rows = await repository.rounds(db, session_id)
    current = rows[-1] if rows else None
    if ended:
        if current is None or current.round != number:
            raise ProblemError(409, "round_order", "End the current round only.")
        current.playback_status = "ended"
        await db.flush()
        return
    if current is not None and current.round == number:
        return
    if (
        number < 1
        or number != (current.round + 1 if current else 1)
        or (current is not None and current.playback_status != "ended")
    ):
        raise ProblemError(409, "round_order", "Play the three rounds in order.")
    await repository.insert_round(db, session_id, session.user_id, number)


RECORDING_TYPES = {"audio/webm": "webm", "audio/mp4": "m4a"}
RECORDING_MAX_BYTES = 5 * 1024 * 1024
REPLAY_TTL_SECONDS = 120


def _round_not_found() -> ProblemError:
    return ProblemError(404, "round_not_found", "There is no such Shadow round.")


async def start_recording_upload(
    db: AsyncSession,
    storage: Storage,
    learner: uuid.UUID,
    session_id: uuid.UUID,
    number: int,
    request: schemas.RecordingRequest,
) -> schemas.RecordingUpload:
    """A signed URL for this round's recording; asking again re-signs the same key.

    The caller has locked the session and checked the Shadow step and voice consent.
    """
    mime = request.mime.split(";", 1)[0].strip().lower()
    if mime not in RECORDING_TYPES:
        raise ProblemError(422, "recording_type", "Recordings must be audio/webm or audio/mp4.")
    if not 1 <= request.size_bytes <= RECORDING_MAX_BYTES:
        raise ProblemError(422, "recording_size", "A recording must be 1 byte to 5 MB.")
    row = next((r for r in await repository.rounds(db, session_id) if r.round == number), None)
    if row is None or row.playback_status != "ended":
        raise ProblemError(409, "round_order", "Finish playing the round before uploading.")
    if row.recorded_at is not None:
        raise ProblemError(409, "recording_exists", "This round already has a recording.")
    previous = row.recording_key
    row.recording_key = (
        f"users/{learner}/shadow/{session_id}/round-{number}-{row.id}.{RECORDING_TYPES[mime]}"
    )
    row.recording_mime = mime
    row.recording_bytes = request.size_bytes
    await db.flush()
    if previous is not None and previous != row.recording_key:
        await storage.delete(previous)  # another type was asked for: no orphaned voice data
    signed = storage.signed_upload(row.recording_key, mime, content_length=request.size_bytes)
    return schemas.RecordingUpload(
        round_id=row.id,
        upload=schemas.RecordingTarget(
            url=signed.url,
            method=signed.method,
            headers=signed.headers,
            expires_at=datetime.fromtimestamp(signed.expires_at, UTC),
        ),
    )


async def complete_recording(
    db: AsyncSession, storage: Storage, round_id: uuid.UUID, version: int
) -> None:
    """Mark the round recorded and done once the object is in storage (ADR 0050 option a).

    No analysis is queued: grading is not built yet, so the learner sees feedback as
    unavailable. Three uploaded recordings complete the plan (FR-SH-6, SR-6).
    """
    found = await repository.round_by_id(db, round_id)
    if found is None:
        raise _round_not_found()
    await practice.lock_session(db, found.session_id)
    session = await practice.require_reached(db, found.session_id, practice.Step.SHADOW)
    row = await repository.round_by_id(db, round_id, lock=True)
    if row is None:
        raise _round_not_found()
    if row.recorded_at is not None:
        return
    practice.require_version(session, version)
    session = await practice.require_step(db, found.session_id, practice.Step.SHADOW)
    if row.recording_key is None or row.recording_mime is None:
        raise ProblemError(409, "round_order", "Ask for an upload URL first.")
    stored = await storage.head(row.recording_key)
    if stored is None:
        raise ProblemError(
            409, "upload_incomplete", "We have not received the recording yet. Try again."
        )
    if stored.size != row.recording_bytes:
        await storage.delete(row.recording_key)
        raise ProblemError(
            409, "upload_size_mismatch", "The recording we received is not the size you sent."
        )
    if (stored.content_type or "").split(";", 1)[0].lower() != row.recording_mime:
        await storage.delete(row.recording_key)
        raise ProblemError(
            409, "upload_type_mismatch", "The recording we received is not the type you sent."
        )
    now = datetime.now(UTC)
    row.recorded_at = now
    row.uploaded_at = now
    await db.flush()
    rounds = await repository.rounds(db, row.session_id)
    # `recorded_at` stays after retention clears an old recording (FR-SH-17), so it, not
    # `uploaded_at`, says that a round was recorded.
    if len(rounds) == 3 and all(r.recorded_at is not None for r in rounds):
        await practice.complete_step(db, session, practice.Step.SHADOW)


async def recording_url(db: AsyncSession, storage: Storage, round_id: uuid.UUID) -> str:
    row = await repository.round_by_id(db, round_id)
    if row is None:
        raise _round_not_found()
    if row.uploaded_at is None or row.recording_key is None:
        raise ProblemError(409, "recording_not_ready", "This round has no saved recording.")
    return storage.signed_download(row.recording_key, ttl_seconds=REPLAY_TTL_SECONDS).url


async def require_round(db: AsyncSession, round_id: uuid.UUID) -> None:
    """404 `round_not_found` unless the round is the signed-in learner's."""
    if await repository.round_by_id(db, round_id) is None:
        raise _round_not_found()


async def discard_upload(db: AsyncSession, storage: Storage, round_id: uuid.UUID) -> None:
    """Drop an unfinished upload, as when voice consent was withdrawn before completion."""
    row = await repository.round_by_id(db, round_id)
    if row is not None and row.recorded_at is None and row.recording_key is not None:
        await storage.delete(row.recording_key)


async def content_deletion_prefixes(learner: uuid.UUID, sessions: list[uuid.UUID]) -> list[str]:
    """A session prefix covers pending recordings and every offered MIME type."""
    return [f"users/{learner}/shadow/{session}/" for session in sessions]
