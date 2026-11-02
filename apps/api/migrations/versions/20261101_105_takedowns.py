"""Takedowns of uploaded media: the record, and media removed by one (#105, ADR 0098).

`ops.takedowns` (Database Design 7) keeps one row per taken-down source, found by a
fingerprint without any learner id (`upload:<sha256>`), so the same file is refused
for every learner afterwards. A media object removed by a takedown keeps its row, so
the learners' sessions, marks and cards stay, with status `removed` and the takedown
that removed it. The YouTube half (#38) widens the fingerprint check.
"""

from alembic import op

revision = "105_takedowns"
down_revision = "90_session_deletion"
branch_labels = None
depends_on = None

STATUSES = "'pending', 'downloading', 'playable', 'failed', 'expired'"


def upgrade() -> None:
    # No user_id and no learner data, so no row-level security: the administrator's
    # request writes it and the learner's content page reads only its grounds.
    op.execute(f"""
CREATE TABLE ops.takedowns (
  id          uuid PRIMARY KEY,
  fingerprint text NOT NULL CHECK (fingerprint ~ '^upload:[0-9a-f]{{64}}$'),
  grounds     text NOT NULL CHECK (grounds IN ('copyright', 'other_rights', 'unlawful')),
  reason      text NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 2000),
  received_at timestamptz NOT NULL DEFAULT now(),
  actioned_at timestamptz,
  report      jsonb CHECK (report IS NULL OR jsonb_typeof(report) = 'object')
);
CREATE UNIQUE INDEX takedowns_fingerprint_idx ON ops.takedowns (fingerprint);
CREATE INDEX takedowns_unactioned_idx ON ops.takedowns (received_at) WHERE actioned_at IS NULL;
GRANT SELECT, INSERT ON ops.takedowns TO listenup_api;
GRANT SELECT, INSERT, UPDATE ON ops.takedowns TO listenup_worker;

ALTER TABLE content.media_objects
  ADD COLUMN takedown_id uuid REFERENCES ops.takedowns (id) ON DELETE RESTRICT,
  DROP CONSTRAINT media_objects_status_check,
  ADD CONSTRAINT media_objects_status_check CHECK (status IN ({STATUSES}, 'removed')),
  ADD CONSTRAINT media_objects_removed_by_takedown
    CHECK ((status = 'removed') = (takedown_id IS NOT NULL));
CREATE INDEX media_objects_takedown_idx ON content.media_objects (takedown_id)
  WHERE takedown_id IS NOT NULL;
""")


def downgrade() -> None:
    # Dropping the records would let a taken-down file be added again.
    op.execute(f"""
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM ops.takedowns) THEN
  RAISE EXCEPTION 'Takedowns are recorded; keep this revision (docs/runbooks/takedowns.md)';
 END IF;
END $$;
DROP INDEX content.media_objects_takedown_idx;
ALTER TABLE content.media_objects
  DROP CONSTRAINT media_objects_removed_by_takedown,
  DROP CONSTRAINT media_objects_status_check,
  ADD CONSTRAINT media_objects_status_check CHECK (status IN ({STATUSES})),
  DROP COLUMN takedown_id;
DROP TABLE ops.takedowns;
""")
