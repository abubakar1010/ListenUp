"""Three playback rounds, distinct from recording completion (FR-SH-2/3)."""

from alembic import op

from migrations.rls import enable_own_rows

revision = "79_shadow_rounds"
down_revision = "76_reference_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(f"""
ALTER TABLE practice.shadow_segments
 ADD CONSTRAINT shadow_segments_session_user_uq UNIQUE (session_id,user_id);
CREATE TABLE practice.shadow_rounds (
 id uuid PRIMARY KEY,
 session_id uuid NOT NULL,
 user_id uuid NOT NULL,
 round int2 NOT NULL CHECK (round BETWEEN 1 AND 3),
 transcript_shown boolean GENERATED ALWAYS AS (round = 1) STORED,
 playback_status text NOT NULL DEFAULT 'ready' CHECK (playback_status IN ('ready','ended')),
 created_at timestamptz NOT NULL DEFAULT now(),
 recorded_at timestamptz,
 UNIQUE (session_id,round),
 CONSTRAINT shadow_rounds_segment_user_fk FOREIGN KEY (session_id,user_id)
 REFERENCES practice.shadow_segments(session_id,user_id) ON DELETE CASCADE
);
GRANT SELECT, INSERT, UPDATE ON practice.shadow_rounds TO listenup_api;
{enable_own_rows("practice.shadow_rounds")}
CREATE FUNCTION practice.check_shadow_round() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous int; ended text;
BEGIN
 IF TG_OP = 'UPDATE' THEN
   IF (NEW.id,NEW.session_id,NEW.user_id,NEW.round) IS DISTINCT FROM
      (OLD.id,OLD.session_id,OLD.user_id,OLD.round)
      OR (OLD.playback_status = 'ended' AND NEW.playback_status <> 'ended') THEN
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
 IF NEW.round NOT BETWEEN 1 AND 3 OR NEW.round <> previous+1 OR NEW.playback_status <> 'ready' THEN
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
CREATE TRIGGER shadow_round_order BEFORE INSERT OR UPDATE ON practice.shadow_rounds
 FOR EACH ROW EXECUTE FUNCTION practice.check_shadow_round();
""")


def downgrade() -> None:
    op.execute("""DROP TABLE practice.shadow_rounds;
DROP FUNCTION practice.check_shadow_round();
ALTER TABLE practice.shadow_segments DROP CONSTRAINT shadow_segments_session_user_uq;""")
