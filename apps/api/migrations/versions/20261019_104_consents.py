"""Versioned consents to terms, privacy and voice recording (#104, FR-SH-17, ADR 0048)."""

from alembic import op

from migrations.rls import enable_own_rows

revision = "104_consents"
down_revision = "57_transcript_corrections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Database Design 3. One row per accepted version, so the history of which
    # versions a learner accepted stays; withdrawing sets withdrawn_at (voice only,
    # enforced by the identity service). The API grants and withdraws, never deletes:
    # rows go with the account through the cascade.
    op.execute(f"""
CREATE TABLE identity.consents (
  user_id      uuid NOT NULL REFERENCES identity.users ON DELETE CASCADE,
  kind         text NOT NULL CHECK (kind IN ('terms', 'privacy', 'voice_recording')),
  version      text NOT NULL CHECK (char_length(version) <= 20),
  granted_at   timestamptz NOT NULL DEFAULT now(),
  withdrawn_at timestamptz,
  PRIMARY KEY (user_id, kind, version)
);
{enable_own_rows("identity.consents")}
GRANT SELECT, INSERT, UPDATE ON identity.consents TO listenup_api;
""")


def downgrade() -> None:
    op.execute("DROP TABLE identity.consents")
