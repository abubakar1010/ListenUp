"""Seed for the B5 load test (#94): N learners, each signed in, with the fixture
script's clip and sessions at every step (seed.py), a cached transcript so Transcript
reads and marks work, extra clips as history, and fresh Blind sessions for the
learners who send heartbeats.

Used by scripts/seed_load.py; it imports nothing from pytest. Writes as the database
owner, like seed.py. The manifest it returns holds session tokens: keep it out of the
repository and delete it after the run (the runner does), and delete the learners with
`delete_learners` once the run is over.
"""

import asyncio
import json
import os
import uuid
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg

from listenup.modules.identity import repository as identity
from listenup.modules.identity.domain.tokens import new_token, token_hash
from listenup.modules.identity.service import session_cookie_name
from listenup.modules.practice import service as practice
from listenup.modules.practice.service import Entry
from listenup.platform.config import Settings
from listenup.platform.csrf import csrf_cookie_name
from listenup.platform.database import Database
from tests.integration.dictation_helpers import seed_transcript
from tests.integration.seed import (
    PASSAGE,
    add_clip,
    add_sessions,
    create_learner,
    seed_learner_data,
    sqlalchemy_ready,
)

# Ten words a second apart from 1 s: k6 marks words 5 and 6, clear of the seeded mark.
TRANSCRIPT_WORDS = [
    "Cities",
    "plant",
    "street",
    "trees",
    "to",
    "cool",
    "the",
    "air",
    "in",
    "summer.",
]


async def add_auth_session(owner_url: str, user_id: uuid.UUID, days: int = 2) -> str:
    """A login session as sign-in makes it; returns the cookie's token.

    Seeded rather than signed in through the API, whose per-IP sign-in limit would
    refuse N learners from one load generator.
    """
    token = new_token()
    database = Database(sqlalchemy_ready(owner_url), pool_size=1)
    try:
        async with database.transaction(user_id) as db:
            await identity.create_auth_session(
                db,
                session_id=uuid.uuid4(),
                user_id=user_id,
                token_hash=token_hash(token),
                lifetime=timedelta(days=days),
                user_agent="listenup-b5-load-test",
                ip=None,
            )
    finally:
        await database.dispose()
    return token


async def add_blind_sessions(
    owner_url: str, user_id: uuid.UUID, content_id: uuid.UUID, count: int
) -> list[uuid.UUID]:
    """`count` new sessions open at Blind, through the practice service."""
    database = Database(sqlalchemy_ready(owner_url), pool_size=1)
    ids: list[uuid.UUID] = []
    try:
        for _ in range(count):
            async with database.transaction(user_id) as db:
                session = await practice.start_session(db, user_id, content_id, PASSAGE, Entry.BOTH)
            ids.append(session.id)
    finally:
        await database.dispose()
    return ids


def seed_load(
    owner_url: str,
    *,
    learners: int,
    history: int,
    blind_learners: int,
    blind_sessions: int,
    password_hash: str | None = None,
    secure_cookies: bool | None = None,
) -> dict[str, Any]:
    """The load-test world as a JSON-ready manifest. The first `blind_learners`
    learners get `blind_sessions` fresh Blind sessions each."""
    secure = Settings().cookies_secure if secure_cookies is None else secure_cookies
    rows: list[dict[str, Any]] = []
    for index in range(learners):
        user_id = create_learner(
            owner_url, f"b5-{index}-{uuid.uuid4().hex[:8]}@example.com", password_hash
        )
        seeded = seed_learner_data(owner_url, user_id)
        seed_transcript(owner_url, seeded.media_id, TRANSCRIPT_WORDS)
        for number in range(history):
            _, content_id, _ = add_clip(owner_url, user_id, f"Earlier clip {number + 1}")
            asyncio.run(add_sessions(owner_url, user_id, content_id))
        fresh = (
            asyncio.run(add_blind_sessions(owner_url, user_id, seeded.content_id, blind_sessions))
            if index < blind_learners
            else []
        )
        rows.append(
            {
                "user_id": str(user_id),
                "token": asyncio.run(add_auth_session(owner_url, user_id)),
                "content_id": str(seeded.content_id),
                "sessions": {stage: str(sid) for stage, sid in seeded.sessions.items()},
                "dictation_attempt_id": str(seeded.dictation_attempt_id),
                "mark_id": str(seeded.mark_id),
                "card_id": str(seeded.card_id),
                "blind_sessions": [str(sid) for sid in fresh],
            }
        )
    return {
        "cookies": {"session": session_cookie_name(secure), "csrf": csrf_cookie_name(secure)},
        "passage": {"start_ms": PASSAGE.start_ms, "end_ms": PASSAGE.end_ms},
        "learners": rows,
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Write the manifest readable by its owner only, from the moment it exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)  # an older copy keeps its mode through O_CREAT
    with os.fdopen(fd, "w") as file:
        file.write(json.dumps(manifest) + "\n")


def delete_learners(owner_url: str, user_ids: Sequence[str]) -> int:
    """Remove seeded learners; their data and login sessions go with them (cascades)."""
    with psycopg.connect(owner_url, autocommit=True) as conn:
        deleted = conn.execute(
            "DELETE FROM identity.users WHERE id = ANY(%s::uuid[])", [list(user_ids)]
        )
        return deleted.rowcount
