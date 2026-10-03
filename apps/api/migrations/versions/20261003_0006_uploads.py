"""Uploads: files a learner is sending straight to storage (#35, ADR 0020).

`POST /uploads` records the declared file here and returns a signed PUT URL;
`POST /contents` confirms the row once the object is in storage, creating the media
object and the learner's content item. The table is what the server remembers between
the two calls, what the 2 GB per-account cap (D5) is counted from, and what a sweep of
abandoned objects reads (`uploads_unconfirmed_idx`).

A confirmed upload belongs to its content item: deleting the item deletes the row.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op

from migrations.rls import disable_own_rows, enable_own_rows

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = f"""
CREATE TABLE content.uploads (
  id              uuid PRIMARY KEY,
  user_id         uuid NOT NULL REFERENCES identity.users ON DELETE CASCADE,
  storage_key     text NOT NULL UNIQUE,     -- users/<user id>/uploads/<upload id>.<ext>
  filename        text NOT NULL CHECK (char_length(filename) BETWEEN 1 AND 255),
  content_type    text NOT NULL CHECK (char_length(content_type) BETWEEN 1 AND 100),
  size_bytes      int8 NOT NULL CHECK (size_bytes > 0),
  content_id      uuid UNIQUE REFERENCES content.contents ON DELETE CASCADE,
  media_object_id uuid REFERENCES content.media_objects ON DELETE CASCADE,
  created_at      timestamptz NOT NULL DEFAULT now(),
  confirmed_at    timestamptz,
  CHECK ((confirmed_at IS NULL) = (content_id IS NULL)),
  CHECK ((content_id IS NULL) = (media_object_id IS NULL))
);
CREATE INDEX uploads_user_idx ON content.uploads (user_id, created_at);
CREATE INDEX uploads_unconfirmed_idx ON content.uploads (created_at)
  WHERE confirmed_at IS NULL;

GRANT SELECT, INSERT, UPDATE, DELETE ON content.uploads TO listenup_api;
{enable_own_rows("content.uploads")}
"""

DOWNGRADE = f"""
{disable_own_rows("content.uploads")}
DROP TABLE content.uploads;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
