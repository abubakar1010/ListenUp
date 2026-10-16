"""Shared passage transcription cache (#45, FR-TX-1, FR-TX-3, NFR-AI-5)."""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE content.passage_transcripts (
  id              uuid PRIMARY KEY,
  media_object_id uuid NOT NULL REFERENCES content.media_objects ON DELETE CASCADE,
  span            int4range NOT NULL CHECK (NOT isempty(span) AND NOT lower_inf(span)
                     AND NOT upper_inf(span) AND lower(span) >= 0),
  origin          text NOT NULL CHECK (origin IN ('creator_captions', 'generated')),
  status          text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'ready', 'failed')),
  words           text[] NOT NULL DEFAULT '{}',
  start_ms        int4[] NOT NULL DEFAULT '{}',
  end_ms          int4[] NOT NULL DEFAULT '{}',
  confidence      int2[] NOT NULL DEFAULT '{}',   -- 0 to 1000
  sentence_starts int4[] NOT NULL DEFAULT '{}',   -- index of each sentence's first word
  provider_info   jsonb NOT NULL DEFAULT '{}',    -- provider, model, version
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  CHECK (cardinality(words) = cardinality(start_ms)
     AND cardinality(words) = cardinality(end_ms)
     AND cardinality(words) = cardinality(confidence)),
  CHECK (array_position(confidence, NULL) IS NULL
     AND 0 <= ALL(confidence) AND 1000 >= ALL(confidence)),
  CHECK (array_position(sentence_starts, NULL) IS NULL
     AND 0 <= ALL(sentence_starts) AND cardinality(words) > ALL(sentence_starts)),
  CHECK (status <> 'ready' OR (
      jsonb_typeof(provider_info) = 'object'
      AND provider_info ?& ARRAY['provider','model','version']
      AND jsonb_typeof(provider_info->'provider') = 'string'
      AND length(provider_info->>'provider') > 0
      AND jsonb_typeof(provider_info->'model') = 'string'
      AND length(provider_info->>'model') > 0
      AND jsonb_typeof(provider_info->'version') = 'string'
      AND length(provider_info->>'version') > 0)),
  -- Cached spans of one media object never overlap; a new passage stores only the missing part.
  EXCLUDE USING gist (media_object_id WITH =, span WITH &&) WHERE (status <> 'failed')
);

CREATE TRIGGER passage_transcripts_touch BEFORE UPDATE ON content.passage_transcripts
  FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
REVOKE ALL ON content.passage_transcripts FROM listenup_api, listenup_readonly;
GRANT SELECT, INSERT, UPDATE, DELETE ON content.passage_transcripts TO listenup_worker;
""")


def downgrade() -> None:
    op.execute("DROP TABLE content.passage_transcripts")
