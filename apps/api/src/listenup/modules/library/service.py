"""Library orchestration through the owning modules' public boundaries (DR-2)."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.cards import service as cards
from listenup.modules.content import service as content
from listenup.modules.identity import service as identity
from listenup.modules.library import jobs
from listenup.modules.practice import service as practice
from listenup.modules.shadow import service as shadow
from listenup.platform.jobs import enqueue


async def delete_content(db: AsyncSession, learner: uuid.UUID, target: uuid.UUID) -> uuid.UUID:
    media, source = await content.mark_for_deletion(db, learner, target)
    # Snapshot under the content lock before a conversion can cascade upload rows.
    # Do not lock children here: mode requests lock session before content.
    sessions = await practice.content_deletion_sessions(db, learner, target, lock=False)
    prefixes, keys = await content.deletion_objects(db, learner, target, media, source)
    card_prefixes = await cards.content_deletion_snapshot(db, learner, sessions)
    prefixes += card_prefixes + await shadow.content_deletion_prefixes(learner, sessions)
    request = await identity.content_deletion_request(
        db,
        learner,
        target,
        {
            "media_id": str(media),
            "source": source,
            "keys": keys,
            "card_prefixes": card_prefixes,
            "sessions_removed": len(sessions),
            "objects_removed": 0,
            "resource_ids": [
                str(value)
                for value in await practice.content_deletion_resource_ids(db, learner, sessions)
            ],
        },
        prefixes,
    )
    await enqueue(
        db,
        jobs.DELETE_CONTENT,
        unique_key=f"content-delete:{request}",
        lock=f"content-delete:{request}",
        request_id=str(request),
    )
    return request
