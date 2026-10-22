"""Marks: places where the sound did not match the text (#58, FR-TR-2, Database Design 5).

A mark covers a word range of the passage (`word_from` to `word_to`, inclusive, in the
passage word sequence) and keeps the audio time of its first word. The table is the
full design table, so tags (#61) and Dictation pre-fill (#55, #59) only add code: the
tag column, the `dictation` source and the `suggested` status are already here.
A mark references its session together with its learner, so it can never belong to
another learner; deleting the session or the account removes it.
"""

from alembic import op

from migrations.rls import disable_own_rows, enable_own_rows

revision = "58_marks"
down_revision = "104_consents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(f"""
CREATE TABLE practice.marks (
  id         uuid PRIMARY KEY,
  session_id uuid NOT NULL,
  user_id    uuid NOT NULL,
  word_from  int4 NOT NULL CHECK (word_from >= 0),
  word_to    int4 NOT NULL,
  at_ms      int4 NOT NULL CHECK (at_ms >= 0),
  tag        text CHECK (tag IN ('linking', 'reduction', 'weak_form', 'unknown_word')),
  note       text CHECK (char_length(note) <= 500),
  source     text NOT NULL CHECK (source IN ('dictation', 'manual')),
  status     text NOT NULL DEFAULT 'confirmed' CHECK (status IN ('suggested', 'confirmed')),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT marks_range_forward CHECK (word_to >= word_from),
  CONSTRAINT marks_session_range_uq UNIQUE (session_id, word_from, word_to),
  CONSTRAINT marks_session_user_fk FOREIGN KEY (session_id, user_id)
    REFERENCES practice.sessions (id, user_id) ON DELETE CASCADE
);
CREATE INDEX marks_session_idx ON practice.marks (session_id, at_ms);
GRANT SELECT, INSERT, UPDATE, DELETE ON practice.marks TO listenup_api;
{enable_own_rows("practice.marks")}
""")


def downgrade() -> None:
    op.execute(f"""
{disable_own_rows("practice.marks")}
DROP TABLE practice.marks;
""")
