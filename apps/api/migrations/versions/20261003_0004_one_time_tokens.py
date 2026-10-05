"""One-time tokens for password reset (and, later, email verification).

Part of the password reset story (#31): FR-ACC-3, NFR-SEC-1; Database Design 3 and
10.3. Only the SHA-256 of a token is stored. Tokens are minted by a background job
(ADR 0017), so the API role never inserts them.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op

from migrations.rls import disable_own_rows, enable_own_rows

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = f"""
CREATE TABLE identity.one_time_tokens (
  token_hash bytea PRIMARY KEY,                -- SHA-256 of the token in the emailed link
  user_id    uuid NOT NULL REFERENCES identity.users ON DELETE CASCADE,
  purpose    text NOT NULL CHECK (purpose IN ('verify_email', 'reset_password')),
  expires_at timestamptz NOT NULL,
  used_at    timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX one_time_tokens_user_idx ON identity.one_time_tokens (user_id, purpose);

-- The API only ever sees its learner's tokens (to retire the others after a reset);
-- workers mint them through their default privileges.
GRANT SELECT, UPDATE ON identity.one_time_tokens TO listenup_api;
{enable_own_rows("identity.one_time_tokens")}

-- A reset link arrives before the learner is known, so, like resolve_auth_session,
-- this function is the one way through row-level security: it marks a live token of
-- the given purpose as used and returns its learner, or NULL when the token is
-- unknown, used or expired. The row lock makes a token work exactly once even when
-- two requests race.
CREATE FUNCTION identity.consume_one_time_token(p_token_hash bytea, p_purpose text)
  RETURNS uuid
  LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
  UPDATE identity.one_time_tokens SET used_at = now()
   WHERE token_hash = p_token_hash AND purpose = p_purpose
     AND used_at IS NULL AND expires_at > now()
  RETURNING user_id
$$;
REVOKE EXECUTE ON FUNCTION identity.consume_one_time_token(bytea, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION identity.consume_one_time_token(bytea, text) TO listenup_api;
"""

DOWNGRADE = f"""
DROP FUNCTION identity.consume_one_time_token(bytea, text);
{disable_own_rows("identity.one_time_tokens")}
DROP TABLE identity.one_time_tokens;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
