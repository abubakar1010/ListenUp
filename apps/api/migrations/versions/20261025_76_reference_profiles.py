"""Limited original reference profiles (#76, ADR 0050)."""

from alembic import op

from migrations.rls import enable_own_rows

revision = "76_reference_profiles"
down_revision = "72_cards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE content.reference_profiles (
 passage_transcript_id uuid REFERENCES content.passage_transcripts ON DELETE CASCADE,
 fingerprint text NOT NULL,
 status text NOT NULL DEFAULT 'pending',
 word_indices int4[] NOT NULL DEFAULT '{}',
 word_start_ms int4[] NOT NULL DEFAULT '{}',
 word_end_ms int4[] NOT NULL DEFAULT '{}',
 word_confidence int2[] NOT NULL DEFAULT '{}',
 pitch_cents int2[] NOT NULL DEFAULT '{}',
 intensity_cdb int2[] NOT NULL DEFAULT '{}',
 frame_step_ms int2 NOT NULL DEFAULT 20,
 provenance jsonb NOT NULL DEFAULT '{}',
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (passage_transcript_id, fingerprint),
 CHECK (status IN ('pending','ready','failed')),
 CHECK (length(fingerprint) = 64),
 CHECK (frame_step_ms = 20),
 CHECK (cardinality(word_indices) = cardinality(word_start_ms) AND cardinality(word_indices) =
cardinality(word_end_ms) AND cardinality(word_indices) = cardinality(word_confidence)),
 CHECK (array_position(word_indices, NULL) IS NULL AND 0 <= ALL(word_indices)),
 CHECK (array_position(word_start_ms, NULL) IS NULL AND 0 <= ALL(word_start_ms)),
 CHECK (array_position(word_end_ms, NULL) IS NULL AND 0 <= ALL(word_end_ms)),
 CHECK (array_position(word_confidence, NULL) IS NULL AND 0 <= ALL(word_confidence) AND 1000 >=
ALL(word_confidence)),
 CHECK (cardinality(pitch_cents) = cardinality(intensity_cdb)),
 CHECK (status <> 'ready' OR (cardinality(pitch_cents) > 0 AND COALESCE(jsonb_typeof(provenance)
= 'object' AND provenance ?& ARRAY['alignment','acoustics','format_version'] AND
provenance->>'format_version' = '1' AND jsonb_typeof(provenance->'alignment') = 'object' AND
provenance->'alignment' ?& ARRAY['provider','model','version'] AND
jsonb_typeof(provenance->'acoustics') = 'object' AND provenance->'acoustics' ?&
ARRAY['provider','model','version','praat_version','settings'] AND
length(provenance->'alignment'->>'provider') > 0 AND length(provenance->'alignment'->>'model') >
0 AND length(provenance->'alignment'->>'version') > 0 AND
length(provenance->'acoustics'->>'version') > 0, false))));

ALTER TABLE content.reference_profiles ADD CONSTRAINT reference_profiles_provenance_types CHECK
(status <> 'ready' OR COALESCE(jsonb_typeof(provenance->'alignment'->'provider') = 'string' AND
length(provenance->'alignment'->>'provider') > 0 AND
jsonb_typeof(provenance->'alignment'->'model') = 'string' AND
length(provenance->'alignment'->>'model') > 0 AND
jsonb_typeof(provenance->'alignment'->'version') = 'string' AND
length(provenance->'alignment'->>'version') > 0 AND
jsonb_typeof(provenance->'acoustics'->'provider') = 'string' AND
length(provenance->'acoustics'->>'provider') > 0 AND
jsonb_typeof(provenance->'acoustics'->'model') = 'string' AND
length(provenance->'acoustics'->>'model') > 0 AND
jsonb_typeof(provenance->'acoustics'->'version') = 'string' AND
length(provenance->'acoustics'->>'version') > 0 AND
jsonb_typeof(provenance->'acoustics'->'praat_version') = 'string' AND
length(provenance->'acoustics'->>'praat_version') > 0 AND
jsonb_typeof(provenance->'acoustics'->'settings') = 'object', false));
REVOKE ALL ON content.reference_profiles FROM listenup_api, listenup_readonly;
GRANT SELECT, INSERT, UPDATE, DELETE ON content.reference_profiles TO listenup_worker;
CREATE TABLE content.profile_subscriptions (
 session_id uuid PRIMARY KEY,
 user_id uuid NOT NULL,
 media_object_id uuid NOT NULL REFERENCES content.media_objects ON DELETE CASCADE,
 span int4range NOT NULL CHECK (NOT isempty(span) AND NOT lower_inf(span) AND NOT
upper_inf(span) AND lower(span) >= 0),
 fingerprint text NOT NULL CHECK (length(fingerprint) = 64),
 status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','ready','failed')),
 FOREIGN KEY (session_id,user_id) REFERENCES practice.sessions(id,user_id) ON DELETE CASCADE
);
GRANT SELECT ON content.profile_subscriptions TO listenup_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON content.profile_subscriptions TO listenup_worker;
CREATE INDEX profile_subscriptions_media_idx ON content.profile_subscriptions(media_object_id);
""")
    op.execute(enable_own_rows("content.profile_subscriptions"))


def downgrade() -> None:
    op.execute("DROP TABLE content.profile_subscriptions")
    op.execute("DROP TABLE content.reference_profiles")
