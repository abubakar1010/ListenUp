"""Intake-lane limited reference profiles (#76, ADRs 0034/0050)."""

import asyncio
import tempfile
import uuid
from pathlib import Path

from listenup.ai.gateway import get_gateway
from listenup.ai.providers.parselmouth_acoustics import extract as extract_acoustics
from listenup.modules.content import service as content
from listenup.modules.transcript import profile_repository as profiles
from listenup.modules.transcript import profile_service, repository, service
from listenup.modules.transcript.models import PassageTranscript
from listenup.modules.transcript.profile_packing import fingerprint as recipe_fingerprint
from listenup.modules.transcript.profile_packing import pack_alignment
from listenup.platform.config import get_settings
from listenup.platform.jobs import JobDeps, Lane, PermanentError, job
from listenup.platform.storage import get_storage


async def extract(source: Path, target: Path, span: tuple[int, int]) -> None:
    # Import locally to avoid registration cycles with transcript.jobs.
    from listenup.modules.transcript.jobs import extract as extract_window

    await extract_window(source, target, span)


async def _give_up(deps: JobDeps, transcript_id: str, fingerprint: str) -> None:
    identifier = uuid.UUID(transcript_id)
    async with (
        repository.media_lock(deps.database, identifier, namespace="profile"),
        deps.database.transaction() as db,
    ):
        transcript = await db.get(PassageTranscript, identifier)
        if transcript is None:
            return
        await profiles.lock(db, transcript.media_object_id)
        row = await profiles.find(db, identifier, fingerprint)
        if row is not None and row.status != "ready":
            await profiles.finish(db, identifier, fingerprint, {"status": "failed"})
            await profiles.settle(db, transcript.media_object_id)


@job(Lane.INTAKE, profile_service.PROFILE, on_give_up=_give_up)
async def profile_span(deps: JobDeps, transcript_id: str, fingerprint: str) -> None:
    try:
        await _profile(deps, uuid.UUID(transcript_id), fingerprint)
    except PermanentError:
        await _give_up(deps, transcript_id, fingerprint)
        raise


async def _profile(deps: JobDeps, identifier: uuid.UUID, fingerprint: str) -> None:
    async with repository.media_lock(deps.database, identifier, namespace="profile"):
        async with deps.database.transaction() as db:
            transcript = await db.get(PassageTranscript, identifier)
            if transcript is None:
                return
            await profiles.lock(db, transcript.media_object_id)
            row = await profiles.find(db, identifier, fingerprint)
            if row is None:
                return
            if row.status == "ready":
                await profiles.settle(db, transcript.media_object_id)
                return
            source = await content.profile_source_for_worker(db, transcript.media_object_id)
        if source is None:
            return
        expected = profile_service.recipe()
        if recipe_fingerprint(expected) != fingerprint:
            raise PermanentError("Profile recipe changed; request the current profile")
        with tempfile.TemporaryDirectory(
            prefix="profile-", dir=get_settings().media_scratch_dir
        ) as scratch:
            playback, audio = Path(scratch) / "playback.mp4", Path(scratch) / "window.wav"
            if await get_storage().download(source.playback_key, playback) is None:
                raise PermanentError("Playback audio is missing")
            await extract(playback, audio, transcript.bounds)
            alignment = await get_gateway().align(audio, " ".join(transcript.words))
            acoustics = await asyncio.to_thread(
                extract_acoustics, audio, transcript.bounds[1] - transcript.bounds[0]
            )
            try:
                packed = pack_alignment(alignment, transcript.words, transcript.bounds)
                if alignment.provenance.model_dump() != expected["alignment"]:
                    raise ValueError("Alignment deployment changed")
                if any(acoustics.provenance.get(k) != v for k, v in expected["acoustics"].items()):
                    raise ValueError("Acoustic deployment changed")
                frame_count = (transcript.bounds[1] - transcript.bounds[0] + 19) // 20
                if (
                    len(acoustics.pitch_cents) != frame_count
                    or len(acoustics.intensity_cdb) != frame_count
                ):
                    raise ValueError("Incomplete acoustic evidence")
            except ValueError as error:
                raise PermanentError("Invalid profile evidence") from error
        async with deps.database.transaction() as db:
            await profiles.lock(db, transcript.media_object_id)
            # Parent deletion wins. Lock the original row before writing its derived data.
            current = await db.get(PassageTranscript, identifier, with_for_update=True)
            if (
                current is None
                or await content.profile_source_for_worker(db, transcript.media_object_id) is None
            ):
                return
            await profiles.finish(
                db,
                identifier,
                fingerprint,
                {
                    **packed,
                    "status": "ready",
                    "pitch_cents": acoustics.pitch_cents,
                    "intensity_cdb": acoustics.intensity_cdb,
                    "provenance": {
                        **expected,
                        "alignment": alignment.provenance.model_dump(),
                        "acoustics": acoustics.provenance,
                    },
                },
            )
            await profiles.settle(db, transcript.media_object_id)


service.on_passage_ready(profile_service.queue_profile)
