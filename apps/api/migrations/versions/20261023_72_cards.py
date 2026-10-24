"""Cards from marks, two live slots per session (FR-CA-1..3, D14)."""

from alembic import op

from migrations.rls import enable_own_rows

revision = "72_cards"
down_revision = "77_shadow_segments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(f"""
CREATE TABLE practice.cards (
  id uuid PRIMARY KEY,
  session_id uuid NOT NULL,
  user_id uuid NOT NULL,
  slot int2 NOT NULL CHECK (slot IN (1, 2)),
  mark_id uuid REFERENCES practice.marks ON DELETE SET NULL,
  media_object_id uuid REFERENCES content.media_objects ON DELETE SET NULL,
  at_ms int4 NOT NULL CHECK (at_ms >= 0),
  written_form text NOT NULL CHECK (char_length(written_form) BETWEEN 1 AND 100),
  heard_form text NOT NULL CHECK (char_length(heard_form) BETWEEN 1 AND 100),
  snippet_key text,
  snippet_span int4range,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT cards_session_user_fk FOREIGN KEY (session_id, user_id)
    REFERENCES practice.sessions (id, user_id) ON DELETE CASCADE,
  UNIQUE (session_id, slot)
);
CREATE INDEX cards_user_idx ON practice.cards (user_id, created_at DESC, id);
GRANT SELECT, INSERT, DELETE ON practice.cards TO listenup_api;
{enable_own_rows("practice.cards")}
""")


def downgrade() -> None:
    op.execute("DROP TABLE practice.cards")
