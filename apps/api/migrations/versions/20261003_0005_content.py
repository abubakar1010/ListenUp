"""Content: shared media objects and each learner's content items.

The tables that intake (#35), the library (#44) and practice sessions (#47) build on,
from Database Design 4, 8.2 and 9.2. Passage transcripts and reference profiles come
with the transcript stories.

Two refinements of the design, both covered by tests/integration/test_content_schema.py:
- contents -> media_objects is NO ACTION, not RESTRICT. Both refuse to delete media
  that a content item still uses, but RESTRICT checks at once, so deleting an account
  failed when the cascade removed the learner's uploaded media before their content
  rows. NO ACTION checks at the end of the statement, after the cascade.
- The reference-count trigger is SECURITY DEFINER: the API role may not update shared
  media rows, yet adding a content item must count the reference.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op

from migrations.rls import CURRENT_LEARNER, disable_own_rows, enable_own_rows

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = f"""
CREATE TABLE content.media_objects (
  id             uuid PRIMARY KEY,
  fingerprint    text NOT NULL UNIQUE,     -- 'youtube:<video id>' or 'upload:<user id>:<sha256>'
  source         text NOT NULL CHECK (source IN ('youtube', 'upload')),
  uploaded_by    uuid REFERENCES identity.users ON DELETE CASCADE,  -- NULL for YouTube
  source_ref     text CHECK (char_length(source_ref) <= 64),        -- YouTube video id
  title          text CHECK (char_length(title) <= 300),
  duration_ms    int4 CHECK (duration_ms > 0),
  has_video      boolean NOT NULL DEFAULT false,
  status         text NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'downloading', 'playable', 'failed', 'expired')),
  error_code     text,
  playback_key   text,                     -- object storage keys
  video_key      text,
  peaks_key      text,
  playback_bytes int8,
  ref_count      int4 NOT NULL DEFAULT 0 CHECK (ref_count >= 0),
  last_used_at   timestamptz NOT NULL DEFAULT now(),
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  CHECK ((source = 'upload') = (uploaded_by IS NOT NULL))
);
CREATE INDEX media_objects_expiry_idx ON content.media_objects (last_used_at)
  WHERE status = 'playable' AND source = 'youtube';
CREATE INDEX media_objects_orphan_idx ON content.media_objects (updated_at)
  WHERE ref_count = 0;
CREATE INDEX media_objects_uploader_idx ON content.media_objects (uploaded_by)
  WHERE uploaded_by IS NOT NULL;
CREATE TRIGGER media_objects_touch BEFORE UPDATE ON content.media_objects
  FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

CREATE TABLE content.contents (
  id              uuid PRIMARY KEY,
  user_id         uuid NOT NULL REFERENCES identity.users ON DELETE CASCADE,
  media_object_id uuid NOT NULL REFERENCES content.media_objects ON DELETE NO ACTION,
  title           text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 300),
  keep_video      boolean NOT NULL DEFAULT false,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, media_object_id)        -- the same clip appears once per library
);
CREATE INDEX contents_library_idx ON content.contents (user_id, created_at DESC, id);
CREATE INDEX contents_media_idx ON content.contents (media_object_id);
CREATE TRIGGER contents_touch BEFORE UPDATE ON content.contents
  FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

-- Reference counting for shared media (System Design 6.2).
CREATE FUNCTION content.count_media_refs() RETURNS trigger
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    UPDATE content.media_objects SET ref_count = ref_count + 1, last_used_at = now()
     WHERE id = NEW.media_object_id;
  ELSE
    UPDATE content.media_objects SET ref_count = ref_count - 1
     WHERE id = OLD.media_object_id;
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER contents_ref_count AFTER INSERT OR DELETE ON content.contents
  FOR EACH ROW EXECUTE FUNCTION content.count_media_refs();

GRANT SELECT, INSERT, UPDATE, DELETE ON content.contents TO listenup_api;
{enable_own_rows("content.contents")}

-- Shared media: a learner sees a media object through their own content item, or as
-- its uploader; the API may create only the learner's own uploads. Workers (BYPASSRLS)
-- do everything else: status, keys, YouTube media, expiry.
GRANT SELECT, INSERT ON content.media_objects TO listenup_api;
GRANT SELECT ON content.media_objects TO listenup_readonly;
ALTER TABLE content.media_objects ENABLE ROW LEVEL SECURITY;
CREATE POLICY via_own_content ON content.media_objects FOR SELECT
  USING (uploaded_by = {CURRENT_LEARNER}
         OR EXISTS (SELECT 1 FROM content.contents c
                     WHERE c.media_object_id = media_objects.id
                       AND c.user_id = {CURRENT_LEARNER}));
CREATE POLICY own_uploads ON content.media_objects FOR INSERT
  WITH CHECK (source = 'upload' AND uploaded_by = {CURRENT_LEARNER});
"""

DOWNGRADE = f"""
DROP POLICY own_uploads ON content.media_objects;
DROP POLICY via_own_content ON content.media_objects;
ALTER TABLE content.media_objects DISABLE ROW LEVEL SECURITY;
{disable_own_rows("content.contents")}
DROP TABLE content.contents;
DROP FUNCTION content.count_media_refs();
DROP TABLE content.media_objects;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
