"""Generation identities and durable snippet write registrations (ADR 0064)."""

from alembic import op

from migrations.rls import enable_own_rows

revision = "73_audio_lifecycle"
down_revision = "73_card_audio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(f"""
ALTER TABLE practice.cards ADD COLUMN audio_generation uuid;
GRANT UPDATE(audio_generation) ON practice.cards TO listenup_api;
CREATE TABLE practice.card_snippet_writes (
 id uuid PRIMARY KEY,
 card_id uuid NOT NULL,
 user_id uuid NOT NULL REFERENCES identity.users(id) ON DELETE RESTRICT,
 owner text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX card_snippet_writes_card_idx ON practice.card_snippet_writes(card_id);
CREATE INDEX card_snippet_writes_user_idx ON practice.card_snippet_writes(user_id);
GRANT SELECT ON practice.card_snippet_writes TO listenup_api;
{enable_own_rows("practice.card_snippet_writes")}
""")


def downgrade() -> None:
    op.execute("""
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM practice.card_snippet_writes) THEN
  RAISE EXCEPTION 'Reconcile snippet writers before downgrading';
 END IF;
END $$;
DROP TABLE practice.card_snippet_writes;
REVOKE UPDATE(audio_generation) ON practice.cards FROM listenup_api;
ALTER TABLE practice.cards DROP COLUMN audio_generation;
""")
