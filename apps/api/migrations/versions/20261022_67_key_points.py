"""Shared, versioned passage key points (#67, NFR-AI-4/5)."""

from alembic import op

revision = "67_key_points"
down_revision = "58_marks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE FUNCTION grading.valid_key_points(points jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE point jsonb; n integer := 0;
BEGIN
  IF jsonb_typeof(points) <> 'array' THEN RETURN false; END IF;
  IF jsonb_array_length(points) NOT BETWEEN 3 AND 6 THEN RETURN false; END IF;
  FOR point IN SELECT value FROM jsonb_array_elements(points) LOOP
    n := n + 1;
    IF NOT COALESCE(
      jsonb_typeof(point) = 'object'
      AND point->>'id' = 'kp' || n::text
      AND jsonb_typeof(point->'text') = 'string'
      AND length(point->>'text') BETWEEN 3 AND 300
      AND point->>'kind' = CASE WHEN n=1 THEN 'main' ELSE 'supporting' END,
      false) THEN RETURN false; END IF;
  END LOOP;
  RETURN true;
END $$;
CREATE TABLE grading.key_points (
  id uuid PRIMARY KEY,
  media_object_id uuid NOT NULL REFERENCES content.media_objects ON DELETE CASCADE,
  span int4range NOT NULL CHECK (
    NOT isempty(span) AND NOT lower_inf(span) AND NOT upper_inf(span) AND lower(span) >= 0),
  prompt_version text NOT NULL CHECK (length(prompt_version) > 0),
  points jsonb NOT NULL CHECK (grading.valid_key_points(points)),
  provider_info jsonb NOT NULL CHECK (
    jsonb_typeof(provider_info) = 'object'
    AND provider_info ?& ARRAY['provider','model','version']
    AND jsonb_typeof(provider_info->'provider') = 'string'
    AND length(provider_info->>'provider') > 0
    AND jsonb_typeof(provider_info->'model') = 'string'
    AND length(provider_info->>'model') > 0
    AND jsonb_typeof(provider_info->'version') = 'string'
    AND length(provider_info->>'version') > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (media_object_id, span, prompt_version)
);
GRANT SELECT, INSERT, UPDATE, DELETE ON grading.key_points TO listenup_worker;
GRANT SELECT ON grading.key_points TO listenup_readonly;
REVOKE ALL ON grading.key_points FROM listenup_api;
""")


def downgrade() -> None:
    op.execute("DROP TABLE grading.key_points; DROP FUNCTION grading.valid_key_points(jsonb)")
