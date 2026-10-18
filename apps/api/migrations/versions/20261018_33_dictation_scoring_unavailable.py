"""A Dictation submission whose passage transcript failed is `scoring_unavailable` (#54).

Grading never blocks the learner: when transcription gives up, the submission leaves
`waiting_transcript` for a state the screen can name, and a later successful
transcription scores it (ADR 0041).
"""

from alembic import op

revision = "33_dictation_scoring_unavailable"
down_revision = "32_google_oidc"
branch_labels = None
depends_on = None

CONSTRAINT = "dictation_attempts_scoring_status_check"


def upgrade() -> None:
    op.execute(f"""
    ALTER TABLE practice.dictation_attempts DROP CONSTRAINT {CONSTRAINT};
    ALTER TABLE practice.dictation_attempts ADD CONSTRAINT {CONSTRAINT}
      CHECK (scoring_status IN ('waiting_transcript', 'scoring_unavailable', 'scored'));
    """)


def downgrade() -> None:
    op.execute(f"""
    UPDATE practice.dictation_attempts
       SET scoring_status = 'waiting_transcript' WHERE scoring_status = 'scoring_unavailable';
    ALTER TABLE practice.dictation_attempts DROP CONSTRAINT {CONSTRAINT};
    ALTER TABLE practice.dictation_attempts ADD CONSTRAINT {CONSTRAINT}
      CHECK (scoring_status IN ('waiting_transcript', 'scored'));
    """)
