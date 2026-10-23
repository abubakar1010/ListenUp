"""Learner-owned gist grades with complete ready results (#68, FR-BL-14)."""

from alembic import op

from migrations.rls import enable_own_rows

revision = "68_gist_grades"
down_revision = "67_key_points"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE grading.gist_grades (
  attempt_id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','ready','unavailable')),
  key_points_id uuid REFERENCES grading.key_points ON DELETE SET NULL,
  dimension_scores jsonb,
  overall int2 CHECK (overall BETWEEN 0 AND 100),
  level text CHECK (level IN ('needs_work','fair','good','excellent')),
  covered_points text[],
  wrong_claims jsonb,
  feedback text CHECK (char_length(feedback) BETWEEN 1 AND 1500),
  rubric_version text CHECK (length(rubric_version) > 0),
  provider_info jsonb,
  attempts_made int2 NOT NULL DEFAULT 0 CHECK (attempts_made >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT gist_grades_attempt_user_fk FOREIGN KEY (attempt_id,user_id)
    REFERENCES practice.attempts(id,user_id) ON DELETE CASCADE,
  CONSTRAINT gist_grades_ready_complete CHECK (
    status <> 'ready' OR (overall IS NOT NULL AND level IS NOT NULL AND feedback IS NOT NULL
      AND rubric_version IS NOT NULL AND provider_info IS NOT NULL)),
  CONSTRAINT gist_grades_provenance CHECK (provider_info IS NULL OR COALESCE(
    jsonb_typeof(provider_info) = 'object'
    AND provider_info ?& ARRAY['provider','model','version','prompt_version']
    AND jsonb_typeof(provider_info->'provider') = 'string'
    AND length(provider_info->>'provider') > 0
    AND jsonb_typeof(provider_info->'model') = 'string'
    AND length(provider_info->>'model') > 0
    AND jsonb_typeof(provider_info->'version') = 'string'
    AND length(provider_info->>'version') > 0
    AND jsonb_typeof(provider_info->'prompt_version') = 'string'
    AND length(provider_info->>'prompt_version') > 0, false))
);
GRANT SELECT, INSERT, UPDATE, DELETE ON grading.gist_grades TO listenup_api, listenup_worker;
""")
    op.execute(enable_own_rows("grading.gist_grades"))


def downgrade() -> None:
    op.execute("DROP TABLE grading.gist_grades")
