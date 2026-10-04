"""Data exports: a learner's requests for a copy of their data (#92, NFR-SEC-5, ADR 0030).

`ops.data_exports` holds one row per export a learner asked for. The API inserts the
row ('pending') and queues the build job in the same transaction; the job (workers'
role) moves it to 'building', then 'ready' with the archive's storage key, or
'failed'. Once its keep period ends the archive is deleted and the row becomes
'expired'; the row itself stays as a record of the request until the account goes.

At most one export per learner is pending or building at a time
(`data_exports_one_live`), so two clicks never build two archives.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-04
"""

from collections.abc import Sequence

from alembic import op

from migrations.rls import disable_own_rows, enable_own_rows

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = f"""
CREATE TABLE ops.data_exports (
  id            uuid PRIMARY KEY,
  user_id       uuid NOT NULL REFERENCES identity.users ON DELETE CASCADE,
  status        text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'building', 'ready', 'failed', 'expired')),
  archive_key   text CHECK (char_length(archive_key) <= 300),  -- users/<id>/exports/<id>.zip
  archive_bytes int8 CHECK (archive_bytes >= 0),
  file_count    int4 CHECK (file_count >= 0),
  error_code    text CHECK (char_length(error_code) <= 100),
  requested_at  timestamptz NOT NULL DEFAULT now(),
  ready_at      timestamptz,
  expires_at    timestamptz,
  CONSTRAINT data_exports_ready_has_archive
    CHECK (status <> 'ready' OR (archive_key IS NOT NULL AND ready_at IS NOT NULL
                                 AND expires_at IS NOT NULL))
);
CREATE INDEX data_exports_user_idx ON ops.data_exports (user_id, requested_at DESC, id);
CREATE UNIQUE INDEX data_exports_one_live ON ops.data_exports (user_id)
  WHERE status IN ('pending', 'building');

-- The API records requests and reads their status; the build and expiry jobs (the
-- workers' role) write everything else.
GRANT SELECT, INSERT ON ops.data_exports TO listenup_api;
{enable_own_rows("ops.data_exports")}
"""

DOWNGRADE = f"""
{disable_own_rows("ops.data_exports")}
DROP TABLE ops.data_exports;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
