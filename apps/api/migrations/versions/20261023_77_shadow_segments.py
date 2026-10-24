"""Shadow segment proposal and immutable round-1 lock (FR-SH-1, C3, D8)."""

from alembic import op

from migrations.rls import enable_own_rows

revision = "77_shadow_segments"
down_revision = "68_gist_grades"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(f"""
CREATE TABLE practice.shadow_segments (
 session_id uuid PRIMARY KEY,
 user_id uuid NOT NULL,
 span int4range NOT NULL,
 chosen_by text NOT NULL CHECK (chosen_by IN ('system', 'learner')),
 mark_count int2 NOT NULL CHECK (mark_count >= 0),
 locked_at timestamptz,
 CONSTRAINT shadow_segments_span CHECK (
   NOT isempty(span) AND NOT lower_inf(span) AND NOT upper_inf(span)
   AND upper(span) - lower(span) BETWEEN 30000 AND 90000),
 CONSTRAINT shadow_segments_session_user_fk FOREIGN KEY (session_id,user_id)
 REFERENCES practice.sessions(id,user_id) ON DELETE CASCADE
);
GRANT SELECT, INSERT, UPDATE ON practice.shadow_segments TO listenup_api;
{enable_own_rows("practice.shadow_segments")}
CREATE FUNCTION practice.check_segment_span() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p int4range;
BEGIN
 SELECT passage INTO p FROM practice.sessions WHERE id = NEW.session_id AND user_id = NEW.user_id;
 IF p IS NOT NULL AND (NOT (NEW.span <@ p) OR NOT (
    (upper(p)-lower(p) <= 60000 AND NEW.span = p)
    OR (upper(p)-lower(p) > 60000 AND upper(NEW.span)-lower(NEW.span) BETWEEN 60000 AND 90000)
 )) THEN
   RAISE EXCEPTION 'segment_span' USING ERRCODE = 'check_violation';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER segments_span BEFORE INSERT OR UPDATE ON practice.shadow_segments
 FOR EACH ROW EXECUTE FUNCTION practice.check_segment_span();
CREATE FUNCTION practice.check_segment_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.locked_at IS NOT NULL AND NEW IS DISTINCT FROM OLD THEN
   RAISE EXCEPTION 'segment_locked' USING ERRCODE = 'check_violation';
 END IF;
 IF NEW.session_id IS DISTINCT FROM OLD.session_id OR NEW.user_id IS DISTINCT FROM OLD.user_id THEN
   RAISE EXCEPTION 'segment_locked' USING ERRCODE = 'check_violation';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER segments_lock BEFORE UPDATE ON practice.shadow_segments
 FOR EACH ROW EXECUTE FUNCTION practice.check_segment_lock();
""")


def downgrade() -> None:
    op.execute("""DROP TABLE practice.shadow_segments;
DROP FUNCTION practice.check_segment_lock();
DROP FUNCTION practice.check_segment_span();""")
