"""Background jobs of the content module (ADR 0015, ADR 0020, ADR 0022)."""

import enum
import logging
import tempfile
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.content import ffmpeg, repository
from listenup.modules.content.domain import admission, media
from listenup.platform.config import get_settings
from listenup.platform.database import Database
from listenup.platform.events import EventType, publish
from listenup.platform.jobs import LANES, JobDeps, Lane, PermanentError, enqueue, job
from listenup.platform.rate_limit import add_to_window
from listenup.platform.storage import S3Storage, Storage

logger = logging.getLogger(__name__)

CONVERT_UPLOAD = "content.convert_upload"


class _Storage:
    """The storage the content jobs use: S3 from the settings, or a fake in tests."""

    instance: Storage | None = None


def use_storage(storage: Storage | None) -> None:
    """Swap the storage the jobs use (tests); None goes back to S3 from the settings."""
    _Storage.instance = storage


def _storage() -> Storage:
    if _Storage.instance is None:
        _Storage.instance = S3Storage(get_settings())
    return _Storage.instance


def daily_audio_key(learner: uuid.UUID) -> str:
    """The learner's count of new audio seconds per day (Database Design 7)."""
    return f"intake:user:{learner}"


async def queue_conversion(
    session: AsyncSession, media_object_id: uuid.UUID, upload_id: uuid.UUID, learner: uuid.UUID
) -> None:
    """Queue validation and conversion of a confirmed upload, in the caller's transaction."""
    await enqueue(
        session,
        CONVERT_UPLOAD,
        unique_key=f"convert_upload:{media_object_id}",
        lock=f"media:{media_object_id}",
        media_object_id=str(media_object_id),
        upload_id=str(upload_id),
        user_id=str(learner),
    )


async def start_waiting_uploads(
    session: AsyncSession, learner: uuid.UUID, running_limit: int
) -> int:
    """Move the learner's oldest waiting uploads onto the shared intake lane (#41).

    At most `running_limit` intakes of one learner are on the lane at once, waiting or
    running; the rest wait in the learner's own queue (`content.uploads.queued_at` is
    NULL), so one learner adding many clips never sits ahead of everyone else (System
    Design 4.2, ADR 0027). Called when an upload is confirmed and whenever one of the
    learner's conversions ends, in that transaction. Returns how many were queued.
    """
    await repository.lock_learner_uploads(session, learner)
    ready = await repository.uploads_to_start(session, learner, running_limit)
    for upload_id, media_id in ready:
        await repository.mark_upload_queued(session, upload_id)
        await queue_conversion(session, media_id, upload_id, learner)
    return len(ready)


async def _conversion_ended(session: AsyncSession, learner: uuid.UUID | None) -> None:
    """A slot on the lane is free: let the learner's next waiting upload in."""
    if learner is not None:
        await start_waiting_uploads(session, learner, get_settings().intake_running_limit)


class _Claim(enum.Enum):
    OURS = "ours"  # the fingerprint now names this media object; convert it
    DUPLICATE = "duplicate"  # the learner already has this file; the new item is gone


@job(Lane.INTAKE, CONVERT_UPLOAD)
async def convert_upload(
    deps: JobDeps, media_object_id: str, upload_id: str, user_id: str | None = None
) -> None:
    """Check and convert an uploaded file into the playback file (#36; FR-CI-1, FR-CI-6).

    Architecture 5.1 (file upload) and System Design 6.1, decided in ADR 0022:

    1. Stream the original from storage into scratch space, hashing it on the way, and
       set the fingerprint `upload:<user id>:<sha256>` (ADR 0020). When the learner
       already has an item on a media object with that fingerprint, the new item is a
       duplicate: it is removed and nothing is converted.
    2. Probe the real streams with ffprobe. Anything that is not accepted audio or
       video, has no sound track or is shorter than 30 s fails for good.
    3. Convert with ffmpeg to the playback file, measure the waveform peaks from the
       same decode, store both under `users/<user id>/media/<media id>/`, set
       `playable` and publish `content.ready` in one transaction.
    4. Delete the original.

    Each step is recorded as the media object's `stage` ('checking', 'converting',
    'saving') and announced with a `job.progress` event, so the learner sees how far it
    has got (FR-CI-5, #40). Making a clip playable counts its new audio towards the
    learner's day (#41), and every way the job ends lets the learner's next waiting
    upload onto the lane.

    Every step can run again: a repeated run on a playable or failed media object
    only makes sure the original is gone.
    """
    media_id = uuid.UUID(media_object_id)
    # Jobs queued before #41 have no user_id; they end without starting the next one.
    learner = uuid.UUID(user_id) if user_id else None
    try:
        await _convert(deps.database, _storage(), media_id, uuid.UUID(upload_id), learner)
    except PermanentError:
        raise
    except Exception:
        # The last attempt must not leave the item processing for ever (FR-CI-5).
        if deps.attempt >= LANES[Lane.INTAKE].max_attempts:
            await _fail(deps.database, media_id, "processing_failed")
        raise


async def _convert(
    database: Database,
    storage: Storage,
    media_id: uuid.UUID,
    upload_id: uuid.UUID,
    learner: uuid.UUID | None,
) -> None:
    async with database.transaction() as session:
        state = await repository.conversion_state(session, media_id, upload_id)
        if state is None:
            await _conversion_ended(session, learner)
    if state is None:
        logger.info("upload conversion skipped: the item is gone", extra={"media": str(media_id)})
        return
    if state.status in ("playable", "failed"):
        await storage.delete(state.source_key)  # a crash may have left it
        return

    settings = get_settings()
    with tempfile.TemporaryDirectory(
        prefix="listenup-convert-", dir=settings.media_scratch_dir
    ) as scratch:
        source = Path(scratch) / "source"
        await _progress(database, media_id, "checking")
        downloaded = await storage.download(state.source_key, source)
        if downloaded is None:
            await _fail(database, media_id, "upload_missing")
            raise PermanentError("the uploaded original is not in storage")

        if (
            await _claim_fingerprint(database, storage, state, downloaded.sha256)
            is _Claim.DUPLICATE
        ):
            await storage.delete(state.source_key)
            return

        try:
            probe = await _probe(source)
            problem = media.check_probe(probe)
            if problem is not None:
                raise _Refused(problem.code, problem.detail)
            target = Path(scratch) / "playback.mp4"
            video = state.keep_video and probe.has_video
            await _progress(database, media_id, "converting")
            try:
                converted = await ffmpeg.convert(source, target, video=video)
            except ffmpeg.ToolFailed as error:
                logger.warning("ffmpeg could not convert an upload", extra={"error": str(error)})
                raise _Refused("conversion_failed", "ffmpeg could not convert the file") from error
        except _Refused as refused:
            await _fail(database, media_id, refused.code)
            await storage.delete(state.source_key)
            raise PermanentError(refused.detail) from refused

        assert probe.duration_ms is not None  # check_probe refuses a file without one
        await _progress(database, media_id, "saving")
        playback = media.playback_key(state.learner, media_id)
        peaks = media.peaks_key(state.learner, media_id)
        await storage.put_file(playback, target, "video/mp4" if video else "audio/mp4")
        await storage.put(peaks, media.peaks_json(converted.peaks), "application/json")
        size = target.stat().st_size

    async with database.transaction() as session:
        stored = await repository.mark_media_playable(
            session,
            media_id,
            duration_ms=probe.duration_ms,
            has_video=video,
            playback_key=playback,
            peaks_key=peaks,
            playback_bytes=size,
        )
        if stored:
            await _announce(session, media_id)
            await add_to_window(
                session,
                daily_audio_key(state.learner),
                admission.DAY,
                admission.counted_seconds(probe.duration_ms),
            )
        await _conversion_ended(session, state.learner)
    if not stored:
        # The learner deleted the item while it converted; nothing refers to the files.
        await storage.delete_prefix(media.media_prefix(state.learner, media_id))
    await storage.delete(state.source_key)
    logger.info(
        "upload converted",
        extra={"media": str(media_id), "duration_ms": probe.duration_ms, "bytes": size},
    )


class _Refused(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


async def _probe(source: Path) -> media.Probe:
    try:
        return await ffmpeg.probe(source)
    except ffmpeg.ToolFailed as error:
        raise _Refused("unsupported_media", "ffprobe cannot read the file as media") from error


async def _claim_fingerprint(
    database: Database, storage: Storage, state: repository.ConversionState, sha256: str
) -> _Claim:
    """Set the real fingerprint, or merge the new item into the learner's existing one.

    Uploads are deduplicated within one learner's library only (ADR 0020, 0022).
    """
    fingerprint = f"upload:{state.learner}:{sha256}"
    if state.fingerprint == fingerprint:
        return _Claim.OURS  # a repeated run
    orphan: uuid.UUID | None = None
    async with database.transaction() as session:
        owner = await repository.fingerprint_owner(session, fingerprint, state.learner)
        if owner is not None and owner.learner_content_id is not None:
            # Same file, already in this library: keep the older item, which may have
            # practice history, and remove the new one. The trigger counts it down. The
            # removed item's page then says which item the learner already has (#39).
            await repository.remember_duplicate(
                session, state.content_id, state.learner, owner.learner_content_id
            )
            await repository.delete_content_item(session, state.content_id)
            await repository.delete_media(session, state.media_id)
            await publish(session, state.learner, EventType.CONTENT_READY, state.content_id)
            await _conversion_ended(session, state.learner)
            logger.info(
                "duplicate upload merged into the existing item",
                extra={"media": str(state.media_id), "existing": str(owner.media_id)},
            )
            return _Claim.DUPLICATE
        if owner is not None:
            if owner.other_references:
                raise RuntimeError("an upload's media object is used by another learner")
            # A leftover of an item the learner deleted: nothing refers to it any more.
            await repository.delete_media(session, owner.media_id)
            orphan = owner.media_id
        await repository.set_fingerprint(session, state.media_id, fingerprint)
    if orphan is not None:
        await storage.delete_prefix(media.media_prefix(state.learner, orphan))
    return _Claim.OURS


async def _fail(database: Database, media_id: uuid.UUID, error_code: str) -> None:
    async with database.transaction() as session:
        changed, learner = await repository.mark_media_failed(session, media_id, error_code)
        if changed:
            await _announce(session, media_id)
            await _conversion_ended(session, learner)
    logger.info("upload refused", extra={"media": str(media_id), "error_code": error_code})


async def _progress(database: Database, media_id: uuid.UUID, stage: media.Stage) -> None:
    """Record how far the job has got and tell the learner (`job.progress`, ADR 0016)."""
    async with database.transaction() as session:
        if await repository.set_media_stage(session, media_id, stage):
            await _announce(session, media_id, EventType.JOB_PROGRESS)


async def _announce(
    session: AsyncSession, media_id: uuid.UUID, event: EventType = EventType.CONTENT_READY
) -> None:
    """Tell each learner with an item on this media object, when the transaction commits."""
    for learner, content_id in await repository.media_content_owners(session, media_id):
        await publish(session, learner, event, content_id)
