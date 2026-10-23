"""Learner-scoped correction writes (#56, FR-TX-4)."""

from alembic import op

revision = "56_dictation_disputes"
down_revision = "68_gist_grades"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("GRANT INSERT, UPDATE, DELETE ON content.transcript_corrections TO listenup_api")
    op.execute("""
CREATE FUNCTION content.delete_learner_corrections() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
  DELETE FROM content.transcript_corrections c
   USING content.passage_transcripts p
   WHERE c.passage_transcript_id=p.id AND c.user_id=OLD.user_id
     AND p.media_object_id=OLD.media_object_id;
  RETURN OLD;
END;
$$;
REVOKE ALL ON FUNCTION content.delete_learner_corrections() FROM PUBLIC;
CREATE TRIGGER delete_learner_corrections AFTER DELETE ON content.contents
FOR EACH ROW EXECUTE FUNCTION content.delete_learner_corrections();
""")


def downgrade() -> None:
    op.execute("DROP TRIGGER delete_learner_corrections ON content.contents")
    op.execute("DROP FUNCTION content.delete_learner_corrections()")
    op.execute("REVOKE INSERT, UPDATE, DELETE ON content.transcript_corrections FROM listenup_api")
