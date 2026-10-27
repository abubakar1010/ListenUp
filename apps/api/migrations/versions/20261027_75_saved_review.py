"""Durable learner-owned review history and global mark ordering."""

from alembic import op

from migrations.rls import enable_own_rows

revision = "75_saved_review"
down_revision = "73_audio_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(f"""
ALTER TABLE practice.cards ADD CONSTRAINT cards_id_user_unique UNIQUE (id, user_id);
CREATE TABLE practice.card_reviews (
 id uuid PRIMARY KEY,
 card_id uuid NOT NULL,
 user_id uuid NOT NULL,
 result text NOT NULL CHECK (result IN ('heard','unsure','missed')),
 reviewed_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY (card_id,user_id) REFERENCES practice.cards(id,user_id) ON DELETE CASCADE
);
CREATE INDEX card_reviews_card_idx ON practice.card_reviews(card_id, reviewed_at DESC, id DESC);
CREATE INDEX marks_user_created_idx ON practice.marks(user_id, created_at DESC, id DESC);
GRANT SELECT, INSERT ON practice.card_reviews TO listenup_api;
{enable_own_rows("practice.card_reviews")}
""")


def downgrade() -> None:
    op.execute(
        "DROP TABLE practice.card_reviews; DROP INDEX practice.marks_user_created_idx; "
        "ALTER TABLE practice.cards DROP CONSTRAINT cards_id_user_unique"
    )
