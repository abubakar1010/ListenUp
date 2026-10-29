"""Retention may clear an expired Shadow recording; the round keeps its time (#93, FR-SH-17)."""

from alembic import op

revision = "93_shadow_retention"
down_revision = "89_content_deletion"
branch_labels = None
depends_on = None

UPGRADE = """
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
      OLD.recording_key,OLD.recording_mime,OLD.recording_bytes)
      -- Retention (FR-SH-17) may clear the whole recording and nothing else.
      AND NOT (OLD.recording_key IS NOT NULL
               AND NEW.recorded_at IS NOT DISTINCT FROM OLD.recorded_at
               AND NEW.recording_key IS NULL AND NEW.recording_mime IS NULL
               AND NEW.recording_bytes IS NULL AND NEW.uploaded_at IS NULL) THEN
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
"""

DOWNGRADE = """
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
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
