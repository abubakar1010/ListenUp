"""Seed a local database with a learner, a clip and a session at each step.

Run from apps/api against a migrated database, as its owner (the default
LISTENUP_DATABASE_URL of the local stack):

    uv run python scripts/seed_dev.py [--email learner@example.com] [--password ...]

It prints the learner's credentials and the ids it made. The clip's media points to
a storage key that holds no file, so the clip lists as playable but does not play.
The data comes from the same fixture script the access test uses
(tests/integration/seed.py; Database Design 12.3).
"""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from listenup.modules.identity.passwords import hash_password
from listenup.platform.config import get_settings
from tests.integration.seed import create_learner, seed_learner_data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", default=f"dev-{uuid.uuid4().hex[:8]}@example.com")
    parser.add_argument("--password", default="listen up locally")
    parser.add_argument("--database-url", default=get_settings().database_url)
    args = parser.parse_args()

    password_hash = asyncio.run(hash_password(args.password))
    user_id = create_learner(args.database_url, args.email, password_hash)
    seeded = seed_learner_data(args.database_url, user_id)

    print(f"learner   {args.email} / {args.password} ({user_id})")
    print(f"clip      {seeded.content_id}")
    print(f"upload    {seeded.pending_upload_id} (not yet confirmed)")
    for stage, session_id in seeded.sessions.items():
        print(f"session   {session_id} at {stage}")
    print(f"dictation {seeded.dictation_attempt_id} (attempt with a draft)")


if __name__ == "__main__":
    main()
