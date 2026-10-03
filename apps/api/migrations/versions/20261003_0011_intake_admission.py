"""Intake admission, progress stages and remembered duplicates (#39, #40, #41; ADR 0027).

- `content.uploads.queued_at`: when the upload's conversion job was put on the shared
  intake lane. A confirmed upload without it waits in the learner's own queue, because
  the learner already has the most intakes allowed on the lane (System Design 4.2).
  Uploads confirmed before this migration were queued at once, so they get their
  confirmation time.
- `content.media_objects.stage`: how far the conversion job has got while the media
  object is still being prepared ('checking', 'converting', 'saving'); NULL otherwise.
  The job announces each change with a `job.progress` event, and the browser reads the
  stage back through the normal endpoints.
- `content.duplicate_uploads`: an item removed because the learner already had the
  same file (ADR 0022), and the item it was merged into, so the removed item's page can
  say "you already have this clip" with a link to it. It goes with either item's
  learner and with the kept item.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op

from migrations.rls import disable_own_rows, enable_own_rows

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = f"""
ALTER TABLE content.uploads ADD COLUMN queued_at timestamptz;
UPDATE content.uploads SET queued_at = confirmed_at WHERE confirmed_at IS NOT NULL;
ALTER TABLE content.uploads
  ADD CONSTRAINT uploads_queued_after_confirmed
  CHECK (queued_at IS NULL OR confirmed_at IS NOT NULL);
-- The learner's own queue: confirmed uploads whose job is not on the lane yet.
CREATE INDEX uploads_waiting_idx ON content.uploads (user_id, confirmed_at, id)
  WHERE confirmed_at IS NOT NULL AND queued_at IS NULL;

ALTER TABLE content.media_objects ADD COLUMN stage text
  CHECK (stage IN ('checking', 'converting', 'saving'));

CREATE TABLE content.duplicate_uploads (
  content_id          uuid PRIMARY KEY,   -- the removed item; no row refers to it any more
  user_id             uuid NOT NULL REFERENCES identity.users ON DELETE CASCADE,
  existing_content_id uuid NOT NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (existing_content_id, user_id)
    REFERENCES content.contents (id, user_id) ON DELETE CASCADE
);
CREATE INDEX duplicate_uploads_existing_idx
  ON content.duplicate_uploads (existing_content_id, user_id);

-- Written by the conversion job (the workers' role); the API only reads it.
GRANT SELECT ON content.duplicate_uploads TO listenup_api;
{enable_own_rows("content.duplicate_uploads")}
"""

DOWNGRADE = f"""
{disable_own_rows("content.duplicate_uploads")}
DROP TABLE content.duplicate_uploads;
ALTER TABLE content.media_objects DROP COLUMN stage;
DROP INDEX content.uploads_waiting_idx;
ALTER TABLE content.uploads DROP CONSTRAINT uploads_queued_after_confirmed;
ALTER TABLE content.uploads DROP COLUMN queued_at;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
