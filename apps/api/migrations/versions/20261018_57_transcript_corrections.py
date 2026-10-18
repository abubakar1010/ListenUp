"""Learner correction storage for Transcript overlays (#57, FR-TX-4)."""

from alembic import op

from migrations.rls import enable_own_rows

revision = "57_transcript_corrections"
down_revision = "0064_ai_gateway"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(f"""
CREATE TABLE content.transcript_corrections (
  user_id uuid NOT NULL REFERENCES identity.users ON DELETE CASCADE,
  passage_transcript_id uuid NOT NULL REFERENCES content.passage_transcripts ON DELETE CASCADE,
  word_index int4 NOT NULL CHECK (word_index >= 0),
  corrected_text text NOT NULL CHECK (char_length(corrected_text) BETWEEN 0 AND 60),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, passage_transcript_id, word_index)
);
{enable_own_rows("content.transcript_corrections")}
GRANT SELECT ON content.transcript_corrections TO listenup_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON content.transcript_corrections TO listenup_worker;
""")


def downgrade() -> None:
    op.execute("DROP TABLE content.transcript_corrections")
