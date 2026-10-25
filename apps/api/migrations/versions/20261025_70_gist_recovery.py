"""Recoverable gist feedback deadlines and quota waits (FR-BL-11)."""

from alembic import op

revision = "70_gist_recovery"
down_revision = "72_cards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE grading.key_point_delays (
  media_object_id uuid NOT NULL REFERENCES content.media_objects ON DELETE CASCADE,
  span int4range NOT NULL,
  prompt_version text NOT NULL,
  PRIMARY KEY (media_object_id, span, prompt_version)
);
GRANT SELECT, INSERT, DELETE ON grading.key_point_delays TO listenup_worker;
ALTER TABLE grading.gist_grades DROP CONSTRAINT gist_grades_status_check;
ALTER TABLE grading.gist_grades ADD CONSTRAINT gist_grades_status_check
  CHECK (status IN ('pending','ready','unavailable','delayed'));
ALTER TABLE grading.gist_grades ADD COLUMN feedback_deadline timestamptz NOT NULL DEFAULT now();
UPDATE grading.gist_grades SET feedback_deadline = created_at + interval '30 seconds';
""")


def downgrade() -> None:
    op.execute("""
DROP TABLE grading.key_point_delays;
UPDATE grading.gist_grades SET status='pending' WHERE status='delayed';
ALTER TABLE grading.gist_grades DROP COLUMN feedback_deadline;
ALTER TABLE grading.gist_grades DROP CONSTRAINT gist_grades_status_check;
ALTER TABLE grading.gist_grades ADD CONSTRAINT gist_grades_status_check
  CHECK (status IN ('pending','ready','unavailable'));
""")
