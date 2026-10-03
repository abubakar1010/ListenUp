"""The fixture script: a learner, a clip and a session at each step (Database Design 12.3).

It writes as the database owner (or any role that bypasses row-level security), the
way a worker or an operator would, and uses the practice service for sessions so
every session passes the same step rules as one the API made.

Used by the cross-learner access test (#34) and by `scripts/seed_dev.py` for local
development. It imports nothing from pytest, so it runs outside the tests too.

    world = seed_learner_data(owner_url, user_id)
    world.sessions["transcript"]   # a session whose open step is Transcript
"""

import asyncio
import uuid
from dataclasses import dataclass, field

import psycopg

from listenup.modules.practice import service as practice
from listenup.modules.practice.service import Entry, Passage, Step
from listenup.platform.database import Database

CLIP_MS = 120_000
PASSAGE = Passage(0, CLIP_MS)
# The session ids are keyed by the step that is open in them; "done" is completed.
SESSION_STAGES = ("blind", "dictation", "transcript", "card", "shadow", "done")


@dataclass(frozen=True)
class SeededLearner:
    """Everything the fixture script made for one learner."""

    user_id: uuid.UUID
    content_id: uuid.UUID
    """A playable clip in the library, added from `confirmed_upload_id`."""
    media_id: uuid.UUID
    confirmed_upload_id: uuid.UUID
    pending_upload_id: uuid.UUID
    """An upload that reached storage but is not yet in the library."""
    pending_upload_key: str
    pending_upload_size: int
    sessions: dict[str, uuid.UUID] = field(default_factory=dict)
    """A session on `content_id` (entry: both) per stage in SESSION_STAGES."""

    def ids(self) -> list[str]:
        """Every id this learner owns, as text: none may appear in another learner's view."""
        return [
            str(value)
            for value in (
                self.user_id,
                self.content_id,
                self.media_id,
                self.confirmed_upload_id,
                self.pending_upload_id,
                *self.sessions.values(),
            )
        ]


def sqlalchemy_ready(url: str) -> str:
    """A postgresql:// URL from a URL or a libpq key=value string."""
    params = psycopg.conninfo.conninfo_to_dict(url)
    return "postgresql://{user}:{password}@{host}:{port}/{dbname}".format(
        user=params.get("user", ""),
        password=params.get("password", ""),
        host=params.get("host", "localhost"),
        port=params.get("port", 5432),
        dbname=params["dbname"],
    )


def create_learner(
    owner_url: str, email: str | None = None, password_hash: str | None = None
) -> uuid.UUID:
    """A learner account; without `password_hash` it cannot sign in with a password."""
    user_id = uuid.uuid4()
    with psycopg.connect(owner_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO identity.users (id, email, password_hash) VALUES (%s, %s, %s)",
            [user_id, email or f"seed-{user_id}@example.com", password_hash],
        )
    return user_id


def add_clip(
    owner_url: str, user_id: uuid.UUID, title: str = "Street trees talk"
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A playable uploaded clip in the learner's library, with its confirmed upload row.

    Returns the ids of the media object, the content item and the upload.
    """
    media_id, content_id, upload_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(owner_url) as conn:
        conn.execute(
            "INSERT INTO content.media_objects "
            "(id, fingerprint, source, uploaded_by, status, duration_ms, playback_key, "
            "peaks_key) VALUES (%s, %s, 'upload', %s, 'playable', %s, %s, %s)",
            [
                media_id,
                f"upload:{user_id}:{media_id.hex}",
                user_id,
                CLIP_MS,
                # The keys the conversion job writes (ADR 0022); no file stands behind them.
                f"users/{user_id}/media/{media_id}/playback.mp4",
                f"users/{user_id}/media/{media_id}/peaks.json",
            ],
        )
        conn.execute(
            "INSERT INTO content.contents (id, user_id, media_object_id, title) "
            "VALUES (%s, %s, %s, %s)",
            [content_id, user_id, media_id, title],
        )
        conn.execute(
            "INSERT INTO content.uploads (id, user_id, storage_key, filename, content_type, "
            "size_bytes, content_id, media_object_id, confirmed_at) "
            "VALUES (%s, %s, %s, 'clip.mp3', 'audio/mpeg', 1000000, %s, %s, now())",
            [upload_id, user_id, f"users/{user_id}/uploads/{upload_id}.mp3", content_id, media_id],
        )
    return media_id, content_id, upload_id


def add_pending_upload(
    owner_url: str, user_id: uuid.UUID, size_bytes: int = 2_000_000
) -> tuple[uuid.UUID, str]:
    """An upload row not yet confirmed; returns its id and storage key."""
    upload_id = uuid.uuid4()
    key = f"users/{user_id}/uploads/{upload_id}.mp3"
    with psycopg.connect(owner_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO content.uploads (id, user_id, storage_key, filename, content_type, "
            "size_bytes) VALUES (%s, %s, %s, 'pending.mp3', 'audio/mpeg', %s)",
            [upload_id, user_id, key, size_bytes],
        )
    return upload_id, key


async def add_sessions(
    owner_url: str, user_id: uuid.UUID, content_id: uuid.UUID
) -> dict[str, uuid.UUID]:
    """One session per stage in SESSION_STAGES, through the practice service."""
    database = Database(sqlalchemy_ready(owner_url), pool_size=1)
    sessions: dict[str, uuid.UUID] = {}
    try:
        for done_steps, stage in enumerate(SESSION_STAGES):
            async with database.transaction(user_id) as db:
                session = await practice.start_session(db, user_id, content_id, PASSAGE, Entry.BOTH)
                for step in list(Step)[:done_steps]:
                    session = await practice.complete_step(db, session, step)
            assert session.current_step == stage, (session.current_step, stage)
            sessions[stage] = session.id
    finally:
        await database.dispose()
    return sessions


def seed_learner_data(owner_url: str, user_id: uuid.UUID) -> SeededLearner:
    """A clip, a pending upload and a session at each step for an existing learner."""
    media_id, content_id, upload_id = add_clip(owner_url, user_id)
    size = 2_000_000
    pending_id, pending_key = add_pending_upload(owner_url, user_id, size)
    sessions = asyncio.run(add_sessions(owner_url, user_id, content_id))
    return SeededLearner(
        user_id=user_id,
        content_id=content_id,
        media_id=media_id,
        confirmed_upload_id=upload_id,
        pending_upload_id=pending_id,
        pending_upload_key=pending_key,
        pending_upload_size=size,
        sessions=sessions,
    )
