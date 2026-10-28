"""Content deletion barrier and durable conversion writers (DR-2; ADR 0085)."""

from alembic import op

from migrations.rls import enable_own_rows

revision = "89_content_deletion"
down_revision = "81_shadow_recordings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(f"""
ALTER TABLE content.contents ADD COLUMN deleting_at timestamptz;
GRANT UPDATE(deleting_at) ON content.contents TO listenup_api;
CREATE TABLE content.media_writes (
 id uuid PRIMARY KEY,
 media_object_id uuid NOT NULL REFERENCES content.media_objects(id) ON DELETE RESTRICT,
 user_id uuid NOT NULL REFERENCES identity.users(id) ON DELETE RESTRICT,
 owner text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX media_writes_media_idx ON content.media_writes(media_object_id);
CREATE INDEX media_writes_user_idx ON content.media_writes(user_id);
GRANT SELECT ON content.media_writes TO listenup_api;
{enable_own_rows("content.media_writes")}
CREATE UNIQUE INDEX deletion_requests_one_open_content_idx
 ON ops.deletion_requests(subject_user_id,target_id)
 WHERE scope='content' AND status IN ('pending','storage_deleted','failed');
""")


def downgrade() -> None:
    op.execute("""
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM content.media_writes) THEN
  RAISE EXCEPTION 'Reconcile conversion writers before downgrading';
 END IF;
END $$;
DROP INDEX ops.deletion_requests_one_open_content_idx;
DROP TABLE content.media_writes;
REVOKE UPDATE(deleting_at) ON content.contents FROM listenup_api;
ALTER TABLE content.contents DROP COLUMN deleting_at;
""")
