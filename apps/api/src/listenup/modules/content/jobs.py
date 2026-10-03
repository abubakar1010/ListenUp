"""Background jobs of the content module (ADR 0015, ADR 0020)."""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.platform.jobs import JobDeps, Lane, enqueue, job

logger = logging.getLogger(__name__)

CONVERT_UPLOAD = "content.convert_upload"


async def queue_conversion(
    session: AsyncSession, media_object_id: uuid.UUID, upload_id: uuid.UUID
) -> None:
    """Queue validation and conversion of a confirmed upload, in the caller's transaction."""
    await enqueue(
        session,
        CONVERT_UPLOAD,
        unique_key=f"convert_upload:{media_object_id}",
        lock=f"media:{media_object_id}",
        media_object_id=str(media_object_id),
        upload_id=str(upload_id),
    )


@job(Lane.INTAKE, CONVERT_UPLOAD)
async def convert_upload(deps: JobDeps, media_object_id: str, upload_id: str) -> None:
    """Validate and convert an uploaded file into the playback file (#36).

    A placeholder until #36: it only logs, and the media object stays `pending`. #36
    fills it in (Architecture 5.1, file upload steps 2 to 4; ADR 0020):

    - read `content.uploads` by `upload_id` for the source key, probe it with ffprobe
      and refuse what is not usable audio or video (`PermanentError`, status `failed`);
    - hash the source while streaming it, and replace the provisional fingerprint
      `upload:<user id>:pending:<upload id>` with `upload:<user id>:<sha256>`; when the
      learner already has a media object with that fingerprint, the new item is a
      duplicate within their library and is handled there;
    - write the playback file, delete the source, set `playable` and publish
      `content.ready`.
    """
    logger.info(
        "upload conversion is not implemented yet; the media object stays pending",
        extra={"media_object_id": media_object_id, "upload_id": upload_id},
    )
