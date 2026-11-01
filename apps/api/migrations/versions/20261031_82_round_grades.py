"""Private per-round delivery evidence and recovery (FR-SH-16/18, E2)."""

from alembic import op

from migrations.rls import enable_own_rows

revision = "82_round_grades"
down_revision = "93_shadow_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE practice.shadow_rounds ADD CONSTRAINT shadow_rounds_id_user_uq UNIQUE(id,user_id);
CREATE TABLE grading.round_grades (
 round_id uuid PRIMARY KEY,
 user_id uuid NOT NULL,
 status text NOT NULL DEFAULT 'pending'
   CHECK (status IN ('pending','scored','ready','unavailable')),
 measures jsonb CHECK (measures IS NULL OR jsonb_typeof(measures) = 'object'),
 overall smallint CHECK (overall BETWEEN 0 AND 100),
 filler_count smallint CHECK (filler_count >= 0),
 word_labels jsonb,
 feedback text CHECK (char_length(feedback) <= 1500),
 top_fixes jsonb,
 feedback_mode text CHECK (feedback_mode IN ('ai','template')),
 speech_info jsonb CHECK (speech_info IS NULL OR COALESCE(jsonb_typeof(speech_info) = 'object'
   AND speech_info ?& ARRAY['provider','model','version','synthetic','parameters_version']
   AND jsonb_typeof(speech_info->'synthetic') = 'boolean'
   AND length(speech_info->>'provider') > 0 AND length(speech_info->>'model') > 0
   AND length(speech_info->>'version') > 0, false)),
 text_info jsonb,
 echo_detected boolean NOT NULL DEFAULT false,
 generation uuid NOT NULL,
 feedback_deadline timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT round_grades_round_user_fk FOREIGN KEY (round_id,user_id)
   REFERENCES practice.shadow_rounds(id,user_id) ON DELETE CASCADE,
 CHECK (status NOT IN ('scored','ready') OR (measures IS NOT NULL AND overall IS NOT NULL
   AND filler_count IS NOT NULL AND speech_info IS NOT NULL))
);
GRANT SELECT, INSERT, UPDATE, DELETE ON grading.round_grades TO listenup_api;
""")
    op.execute(enable_own_rows("grading.round_grades"))


def downgrade() -> None:
    op.execute("""
DROP TABLE grading.round_grades;
ALTER TABLE practice.shadow_rounds DROP CONSTRAINT shadow_rounds_id_user_uq;
""")
