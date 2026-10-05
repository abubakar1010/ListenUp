"""Dictation attempts: the learner's draft and, later, the submitted text and its score.

From Database Design 5 (`practice.dictation_attempts`), for issues #51 and #52. One
row hangs off each Dictation attempt in `practice.attempts` (migration 0008). The
row is referenced together with its learner, so it can never belong to anyone else.
`draft_version` counts saves: a save names the version it was based on, and a stale
one is refused, so two tabs never silently overwrite each other (#50, ADR 0025).
The submission and scoring columns are filled by #53 and #54.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op

from migrations.rls import disable_own_rows, enable_own_rows

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = f"""
CREATE TABLE practice.dictation_attempts (
  attempt_id     uuid PRIMARY KEY,
  user_id        uuid NOT NULL,
  draft_text     text NOT NULL DEFAULT '' CHECK (char_length(draft_text) <= 20000),
  draft_version  int4 NOT NULL DEFAULT 0 CHECK (draft_version >= 0),
  submitted_text text CHECK (char_length(submitted_text) <= 20000),
  scoring_status text CHECK (scoring_status IN ('waiting_transcript', 'scored')),
  diff           jsonb,                  -- per reference word: status and what was typed
  accuracy       numeric(5,2) CHECK (accuracy BETWEEN 0 AND 100),
  scored_at      timestamptz,
  updated_at     timestamptz NOT NULL DEFAULT now(),
  -- The attempt and its learner together: never another learner's attempt.
  CONSTRAINT dictation_attempts_attempt_user_fk FOREIGN KEY (attempt_id, user_id)
    REFERENCES practice.attempts (id, user_id) ON DELETE CASCADE
);
CREATE TRIGGER dictation_attempts_touch BEFORE UPDATE ON practice.dictation_attempts
  FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

GRANT SELECT, INSERT, UPDATE ON practice.dictation_attempts TO listenup_api;
{enable_own_rows("practice.dictation_attempts")}
"""

DOWNGRADE = f"""
{disable_own_rows("practice.dictation_attempts")}
DROP TABLE practice.dictation_attempts;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
