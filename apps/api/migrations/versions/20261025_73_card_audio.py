"""Private card snippets and durable deletion cleanup (FR-CA-2)."""

from alembic import op

from migrations.rls import enable_own_rows

revision = "73_card_audio"
down_revision = "76_reference_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(f"""
ALTER TABLE practice.cards ADD COLUMN audio_status text NOT NULL DEFAULT 'unavailable'
 CHECK (audio_status IN ('unavailable','pending','ready','failed'));
ALTER TABLE practice.cards ADD CONSTRAINT cards_ready_audio CHECK
 (audio_status <> 'ready' OR (snippet_key IS NOT NULL AND snippet_span IS NOT NULL));
ALTER TABLE practice.cards ADD CONSTRAINT cards_snippet_bounds CHECK
 (snippet_span IS NULL OR (NOT isempty(snippet_span) AND NOT lower_inf(snippet_span)
 AND NOT upper_inf(snippet_span) AND lower(snippet_span)>=0
 AND upper(snippet_span)-lower(snippet_span) BETWEEN 3000 AND 6000));
GRANT UPDATE(audio_status) ON practice.cards TO listenup_api;
CREATE TABLE practice.card_snippet_cleanup (
 card_id uuid PRIMARY KEY,
 user_id uuid NOT NULL REFERENCES identity.users(id) ON DELETE CASCADE,
 created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT ON practice.card_snippet_cleanup TO listenup_api;
{enable_own_rows("practice.card_snippet_cleanup")}
CREATE FUNCTION practice.remember_card_snippet() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
 BEGIN
 -- Account purge already sweeps the entire prefix before and after deleting rows.
 IF EXISTS (SELECT 1 FROM identity.users WHERE id=OLD.user_id) THEN
   INSERT INTO practice.card_snippet_cleanup(card_id,user_id)
   VALUES (OLD.id,OLD.user_id) ON CONFLICT DO NOTHING;
 END IF;
 RETURN OLD;
 END $$;
REVOKE ALL ON FUNCTION practice.remember_card_snippet() FROM PUBLIC;
CREATE TRIGGER card_snippet_deleted AFTER DELETE ON practice.cards
 FOR EACH ROW EXECUTE FUNCTION practice.remember_card_snippet();
""")


def downgrade() -> None:
    op.execute("""
DROP TRIGGER card_snippet_deleted ON practice.cards;
DROP FUNCTION practice.remember_card_snippet();
DROP TABLE practice.card_snippet_cleanup;
REVOKE UPDATE(audio_status) ON practice.cards FROM listenup_api;
ALTER TABLE practice.cards DROP CONSTRAINT cards_snippet_bounds;
ALTER TABLE practice.cards DROP CONSTRAINT cards_ready_audio;
ALTER TABLE practice.cards DROP COLUMN audio_status;
""")
