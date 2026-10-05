"""Blind attempts: the server's record of one Blind listen (#62, #63, #65; ADR 0024).

From Database Design 5 (`practice.blind_attempts`), plus the columns the design does
not have yet and the heartbeat rules need (ADR 0024):

- `media_expires_at`: when the attempt-bound media URL stops working (#62);
- `passage_start_ms`, `passage_end_ms`: the session's passage, copied at the start so
  a heartbeat needs one row;
- `anchor_position_ms`, `anchor_at`: where and when playback could have started at
  the earliest (the start, or the resume point), for the cumulative too-fast check;
- `resume_stop_ms`: where the interruption that used the one resume stopped (D13).

`void_reason` also allows `interrupted`: a second interruption, or a device pause of
5 s or more (D13). Fill factor 70 leaves room on each page for HOT updates, since a
row is updated every 5 s while the passage plays.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op

from migrations.rls import disable_own_rows, enable_own_rows

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = f"""
CREATE TABLE practice.blind_attempts (
  attempt_id         uuid PRIMARY KEY,
  user_id            uuid NOT NULL,
  media_token_hash   bytea NOT NULL CHECK (octet_length(media_token_hash) = 32),
  media_expires_at   timestamptz NOT NULL,
  passage_start_ms   integer NOT NULL CHECK (passage_start_ms >= 0),
  passage_end_ms     integer NOT NULL,
  last_position_ms   integer NOT NULL,
  last_heartbeat_at  timestamptz NOT NULL,
  anchor_position_ms integer NOT NULL,
  anchor_at          timestamptz NOT NULL,
  buffering_ms       integer NOT NULL DEFAULT 0 CHECK (buffering_ms BETWEEN 0 AND 20000),
  resume_count       smallint NOT NULL DEFAULT 0 CHECK (resume_count BETWEEN 0 AND 1),
  resume_stop_ms     integer,
  void_reason        text CHECK (void_reason IN
                       ('left_page', 'reload', 'seek', 'missed_heartbeat', 'too_fast',
                        'interrupted')),
  gist_text          text CHECK (char_length(gist_text) <= 2000),
  CONSTRAINT blind_attempts_passage CHECK (passage_end_ms > passage_start_ms),
  CONSTRAINT blind_attempts_resume_stop CHECK ((resume_count = 1) = (resume_stop_ms IS NOT NULL)),
  -- The attempt's own learner, always (composite key, Database Design 5).
  CONSTRAINT blind_attempts_attempt_user_fk FOREIGN KEY (attempt_id, user_id)
    REFERENCES practice.attempts (id, user_id) ON DELETE CASCADE
) WITH (fillfactor = 70);

GRANT SELECT, INSERT, UPDATE ON practice.blind_attempts TO listenup_api;
{enable_own_rows("practice.blind_attempts")}
"""

DOWNGRADE = f"""
{disable_own_rows("practice.blind_attempts")}
DROP TABLE practice.blind_attempts;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
