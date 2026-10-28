"""Content cleanup's real S3 boundary; the other tests inject deterministic failures."""

import asyncio
import uuid

from listenup.platform.storage import use_storage
from tests.integration.intake_helpers import learner_id
from tests.integration.seed import seed_learner_data
from tests.integration.test_content_deletion import delete, make_client, run_delete, storage
from tests.integration.test_storage import storage as s3_storage

__all__ = ["make_client", "s3_storage", "storage"]


def test_content_cleanup_removes_real_objects_and_can_run_again(
    make_client, migrated_url, s3_storage, storage
):
    a = make_client()
    world = seed_learner_data(migrated_url, uuid.UUID(learner_id(a)))
    keys = [
        f"users/{world.user_id}/media/{world.media_id}/playback.mp4",
        f"users/{world.user_id}/uploads/{world.confirmed_upload_id}.mp3",
        f"users/{world.user_id}/cards/{world.card_id}/snippet.m4a",
        f"users/{world.user_id}/shadow/{world.sessions['shadow']}/recording.webm",
    ]
    keep = f"users/{uuid.uuid4()}/media/private/playback.mp4"

    async def put():
        for key in [*keys, keep]:
            await s3_storage.put(key, b"private audio", "audio/mp4")

    asyncio.run(put())
    use_storage(s3_storage)
    try:
        response = delete(a, world.content_id)
        assert response.status_code == 202, response.text
        run_delete(migrated_url, response.json()["request_id"])
        run_delete(migrated_url, response.json()["request_id"])

        async def check():
            for key in keys:
                assert await s3_storage.head(key) is None
            assert await s3_storage.head(keep) is not None

        asyncio.run(check())
    finally:
        use_storage(storage)
