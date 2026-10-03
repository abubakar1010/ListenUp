"""Attempts: one learner's try at a Blind or Dictation step.

Shared by the Blind (#62, #63, #65) and Dictation (#51, #52) stories, from Database
Design 5. Each mode adds its own table that hangs off an attempt
(practice.blind_attempts, practice.dictation_attempts) in its own migration.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op

from migrations.rls import disable_own_rows, enable_own_rows

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = f"""
CREATE TABLE practice.attempts (
  id          uuid PRIMARY KEY,
  session_id  uuid NOT NULL,
  user_id     uuid NOT NULL,
  mode        text NOT NULL CHECK (mode IN ('blind', 'dictation')),
  status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'submitted', 'voided')),
  started_at  timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  CHECK ((status = 'active') = (finished_at IS NULL)),
  -- An attempt exists only for a step this session really has, and is removed with it.
  CONSTRAINT attempts_step_fk FOREIGN KEY (session_id, mode)
    REFERENCES practice.session_steps (session_id, step) ON DELETE CASCADE,
  -- ... and belongs to the session's own learner.
  CONSTRAINT attempts_session_user_fk FOREIGN KEY (session_id, user_id)
    REFERENCES practice.sessions (id, user_id) ON DELETE CASCADE,
  -- Lets each mode's table reference (attempt id, learner) together.
  CONSTRAINT attempts_id_user_uq UNIQUE (id, user_id)
);
-- One live attempt per session and mode (FR-PL-4).
CREATE UNIQUE INDEX attempts_one_active ON practice.attempts (session_id, mode)
  WHERE status = 'active';
CREATE INDEX attempts_session_idx ON practice.attempts (session_id, mode, started_at DESC);

GRANT SELECT, INSERT, UPDATE ON practice.attempts TO listenup_api;
{enable_own_rows("practice.attempts")}
"""

DOWNGRADE = f"""
{disable_own_rows("practice.attempts")}
DROP TABLE practice.attempts;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
