"""Private Shadow round recordings: key, type, size and upload time (FR-SH-5, FR-SH-8)."""

from alembic import op

revision = "81_shadow_recordings"
down_revision = "75_saved_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE practice.shadow_rounds
 ADD COLUMN recording_key text,
 ADD COLUMN recording_mime text,
 ADD COLUMN recording_bytes int,
 ADD COLUMN uploaded_at timestamptz,
 ADD CONSTRAINT shadow_rounds_recording_private CHECK (
  recording_key IS NULL OR (
   char_length(recording_key) <= 300
   AND recording_key LIKE 'users/' || user_id::text || '/shadow/%'
   AND recording_mime IN ('audio/webm','audio/mp4')
   AND recording_bytes BETWEEN 1 AND 5242880)),
 ADD CONSTRAINT shadow_rounds_recording_all_or_none CHECK (
  (recording_key IS NULL) = (recording_mime IS NULL)
  AND (recording_key IS NULL) = (recording_bytes IS NULL)),
 ADD CONSTRAINT shadow_rounds_uploaded CHECK (
  uploaded_at IS NULL OR (recording_key IS NOT NULL AND recorded_at IS NOT NULL));
CREATE INDEX shadow_rounds_expiry_idx ON practice.shadow_rounds (recorded_at)
 WHERE recording_key IS NOT NULL;
CREATE OR REPLACE FUNCTION practice.check_shadow_round() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous int; ended text;
BEGIN
 IF TG_OP = 'UPDATE' THEN
   IF (NEW.id,NEW.session_id,NEW.user_id,NEW.round) IS DISTINCT FROM
      (OLD.id,OLD.session_id,OLD.user_id,OLD.round)
      OR (OLD.playback_status = 'ended' AND NEW.playback_status <> 'ended') THEN
     RAISE EXCEPTION 'round_order' USING ERRCODE = 'check_violation';
   END IF;
   -- A recording can be offered only after playback ended, and is fixed once recorded.
   IF NEW.recording_key IS NOT NULL AND NEW.playback_status <> 'ended' THEN
     RAISE EXCEPTION 'round_order' USING ERRCODE = 'check_violation';
   END IF;
   IF OLD.recorded_at IS NOT NULL AND (NEW.recorded_at,NEW.uploaded_at,NEW.recording_key,
      NEW.recording_mime,NEW.recording_bytes) IS DISTINCT FROM (OLD.recorded_at,OLD.uploaded_at,
      OLD.recording_key,OLD.recording_mime,OLD.recording_bytes) THEN
     RAISE EXCEPTION 'round_order' USING ERRCODE = 'check_violation';
   END IF;
   RETURN NEW;
 END IF;
 -- Same lock order as the service: parent session, then segment.
 PERFORM 1 FROM practice.sessions WHERE id=NEW.session_id AND user_id=NEW.user_id FOR UPDATE;
 PERFORM 1 FROM practice.shadow_segments
 WHERE session_id=NEW.session_id AND user_id=NEW.user_id FOR UPDATE;
 SELECT coalesce(max(round),0) INTO previous FROM practice.shadow_rounds
 WHERE session_id=NEW.session_id;
 IF NEW.round NOT BETWEEN 1 AND 3 OR NEW.round <> previous+1 OR NEW.playback_status <> 'ready'
    OR NEW.recording_key IS NOT NULL OR NEW.recorded_at IS NOT NULL THEN
   RAISE EXCEPTION 'round_order' USING ERRCODE = 'check_violation';
 END IF;
 IF previous > 0 THEN
   SELECT playback_status INTO ended FROM practice.shadow_rounds
   WHERE session_id=NEW.session_id AND round=previous;
   IF ended <> 'ended' THEN RAISE EXCEPTION 'round_order' USING ERRCODE = 'check_violation'; END IF;
 END IF;
 IF NEW.round=1 THEN
   UPDATE practice.shadow_segments SET locked_at=coalesce(locked_at,now())
   WHERE session_id=NEW.session_id AND user_id=NEW.user_id;
 END IF;
 RETURN NEW;
END $$;
""")


def downgrade() -> None:
    op.execute("""
DROP INDEX practice.shadow_rounds_expiry_idx;
ALTER TABLE practice.shadow_rounds
 DROP CONSTRAINT shadow_rounds_uploaded,
 DROP CONSTRAINT shadow_rounds_recording_all_or_none,
 DROP CONSTRAINT shadow_rounds_recording_private,
 DROP COLUMN uploaded_at, DROP COLUMN recording_bytes,
 DROP COLUMN recording_mime, DROP COLUMN recording_key;
""")
