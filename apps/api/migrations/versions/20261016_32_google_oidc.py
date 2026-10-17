"""Google identities and short-lived, browser-bound authentication transactions."""

from alembic import op

from migrations.rls import enable_own_rows

revision = "32_google_oidc"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(f"""
    CREATE TABLE identity.oauth_accounts (
      provider text NOT NULL CHECK (provider IN ('google')),
      subject text NOT NULL CHECK (char_length(subject) BETWEEN 1 AND 255),
      user_id uuid NOT NULL REFERENCES identity.users ON DELETE CASCADE,
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (provider, subject)
    );
    CREATE INDEX oauth_accounts_user_idx ON identity.oauth_accounts (user_id);
    GRANT SELECT, INSERT ON identity.oauth_accounts TO listenup_api;
    {enable_own_rows("identity.oauth_accounts")}
    CREATE FUNCTION identity.google_account(p_subject text) RETURNS uuid
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
      SELECT user_id FROM identity.oauth_accounts WHERE provider = 'google' AND subject = p_subject
    $$;
    REVOKE ALL ON FUNCTION identity.google_account(text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION identity.google_account(text) TO listenup_api;

    CREATE TABLE identity.oidc_flows (
      token_hash bytea PRIMARY KEY,
      browser_hash bytea NOT NULL,
      user_id uuid REFERENCES identity.users ON DELETE CASCADE,
      purpose text NOT NULL CHECK (purpose IN ('login', 'reauth', 'restore', 'delete')),
      data jsonb NOT NULL,
      expires_at timestamptz NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX oidc_flows_expires_idx ON identity.oidc_flows (expires_at);
    GRANT SELECT ON identity.oidc_flows TO listenup_api;
    {enable_own_rows("identity.oidc_flows")}
    -- No public read/write of authentication material. Only trusted API code calls
    -- these narrow functions; possession of both random secrets authorizes consume.
    CREATE FUNCTION identity.put_oidc_flow(p_token bytea, p_browser bytea, p_user uuid,
      p_purpose text, p_data jsonb, p_lifetime int) RETURNS void
      LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
      BEGIN
        DELETE FROM identity.oidc_flows WHERE expires_at <= clock_timestamp();
        INSERT INTO identity.oidc_flows
          (token_hash, browser_hash, user_id, purpose, data, expires_at)
        VALUES (p_token, p_browser, p_user, p_purpose, p_data,
                clock_timestamp() + make_interval(secs => p_lifetime));
      END
    $$;
    CREATE FUNCTION identity.take_oidc_flow(p_token bytea, p_browser bytea, p_purpose text)
      RETURNS jsonb LANGUAGE sql VOLATILE SECURITY DEFINER
      SET search_path = pg_catalog, pg_temp AS $$
      DELETE FROM identity.oidc_flows
       WHERE token_hash = p_token AND browser_hash = p_browser AND purpose = p_purpose
       RETURNING CASE WHEN expires_at > clock_timestamp() THEN data END
    $$;
    CREATE FUNCTION identity.peek_oidc_flow(p_token bytea, p_browser bytea, p_purpose text)
      RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER
      SET search_path = pg_catalog, pg_temp AS $$
      SELECT data FROM identity.oidc_flows
       WHERE token_hash = p_token AND browser_hash = p_browser AND purpose = p_purpose
         AND expires_at > statement_timestamp()
    $$;
    REVOKE ALL ON FUNCTION identity.peek_oidc_flow(bytea, bytea, text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION identity.peek_oidc_flow(bytea, bytea, text) TO listenup_api;
    REVOKE ALL ON FUNCTION identity.put_oidc_flow(bytea, bytea, uuid, text, jsonb, int),
      identity.take_oidc_flow(bytea, bytea, text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION identity.put_oidc_flow(bytea, bytea, uuid, text, jsonb, int),
      identity.take_oidc_flow(bytea, bytea, text) TO listenup_api;
    """)


def downgrade() -> None:
    op.execute("""
    DROP FUNCTION identity.peek_oidc_flow(bytea, bytea, text);
    DROP FUNCTION identity.take_oidc_flow(bytea, bytea, text);
    DROP FUNCTION identity.put_oidc_flow(bytea, bytea, uuid, text, jsonb, int);
    DROP TABLE identity.oidc_flows;
    DROP FUNCTION identity.google_account(text);
    DROP TABLE identity.oauth_accounts;
    """)
