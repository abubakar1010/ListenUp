"""Account deletion with a 7-day grace period (#91, #120; D9; ADR 0029).

- `ops.deletion_requests` (Database Design 7) is written when the learner deletes
  their account, not when the grace period ends, so the request itself records when
  the purge is due and whether a restore cancelled it:
  - `due_at`: when the purge job may start (the end of the grace period; it equals
    `identity.users.deletion_scheduled_at` while the account waits).
  - `cancelled_at` and status 'cancelled': the learner restored the account by
    signing in before `due_at`. A cancelled request is kept as an audit record.
  - `media_object_ids`: the learner's upload media objects when the request was made,
    for the report (their files live under the storage prefix).
  - `failed_at` and status 'failed': the purge gave up after its last attempt (a
    timeout included). The request stays open: the sweep queues it again an hour later,
    resuming where it stopped, because a deletion must finish.
  At most one open account request per learner. There is no foreign key to the
  learner: the request must outlive the account it deletes. Row-level security
  limits the API to the signed-in learner's own requests; the purge job (the workers'
  role) sees them all.
- `identity.resolve_auth_session` returns a learner only while their account is
  active, so a login session that somehow outlived the deletion (or one created
  while the account waited) never reaches data without the restore step.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-04
"""

from collections.abc import Sequence

from alembic import op

from migrations.rls import CURRENT_LEARNER

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = f"""
CREATE TABLE ops.deletion_requests (
  id               uuid PRIMARY KEY,
  subject_user_id  uuid NOT NULL,     -- no foreign key: the audit outlives the account
  scope            text NOT NULL CHECK (scope IN ('account', 'content', 'session', 'recordings')),
  target_id        uuid,
  status           text NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'storage_deleted', 'completed', 'failed',
                                     'cancelled')),
  storage_prefixes text[] NOT NULL DEFAULT '{{}}',
  media_object_ids uuid[] NOT NULL DEFAULT '{{}}',
  report           jsonb,             -- counts of rows and objects removed
  requested_at     timestamptz NOT NULL DEFAULT now(),
  due_at           timestamptz NOT NULL DEFAULT now(),
  cancelled_at     timestamptz,
  completed_at     timestamptz,
  failed_at        timestamptz,       -- the purge's last attempt failed; retried later
  CHECK ((status = 'cancelled') = (cancelled_at IS NOT NULL)),
  CHECK ((status = 'completed') = (completed_at IS NOT NULL)),
  CHECK ((status = 'failed') = (failed_at IS NOT NULL)),
  CHECK (due_at >= requested_at)
);
-- The purge job's sweep: open requests by due time.
CREATE INDEX deletion_requests_due_idx ON ops.deletion_requests (due_at)
  WHERE status IN ('pending', 'storage_deleted', 'failed');
CREATE UNIQUE INDEX deletion_requests_one_open_account_idx
  ON ops.deletion_requests (subject_user_id)
  WHERE scope = 'account' AND status IN ('pending', 'storage_deleted', 'failed');

-- The API writes the request and cancels it on restore; only the purge job (workers,
-- BYPASSRLS) completes it.
GRANT SELECT, INSERT, UPDATE ON ops.deletion_requests TO listenup_api;
GRANT SELECT ON ops.deletion_requests TO listenup_readonly;
ALTER TABLE ops.deletion_requests ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_requests ON ops.deletion_requests
  USING (subject_user_id = {CURRENT_LEARNER})
  WITH CHECK (subject_user_id = {CURRENT_LEARNER});

CREATE OR REPLACE FUNCTION identity.resolve_auth_session(p_token_hash bytea) RETURNS uuid
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
  SELECT s.user_id FROM identity.auth_sessions s
    JOIN identity.users u ON u.id = s.user_id
   WHERE s.token_hash = p_token_hash AND s.expires_at > now() AND u.status = 'active'
$$;
"""

DOWNGRADE = """
CREATE OR REPLACE FUNCTION identity.resolve_auth_session(p_token_hash bytea) RETURNS uuid
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
  SELECT user_id FROM identity.auth_sessions
   WHERE token_hash = p_token_hash AND expires_at > now()
$$;
DROP TABLE ops.deletion_requests;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
