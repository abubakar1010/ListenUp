"""Baseline: extensions, schemas, roles, row-level security, users and login sessions.

Implements the migration baseline story (#27): Database Design sections 1, 3, 9 and
12.3; NFR-SEC-2 and FR-ACC-2. Feature tables are added by their own stories.

Revision ID: 0001
Revises:
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op

from migrations.rls import disable_own_rows, enable_own_rows

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMAS = "identity, content, practice, grading, ai, ops"

# Service roles (Database Design 9.1). Roles belong to the whole PostgreSQL cluster,
# so they are created only when missing and are never dropped by a downgrade. They
# are NOLOGIN here; each environment enables login with a password from its secrets
# (ALTER ROLE listenup_api LOGIN PASSWORD ...). The role that runs these migrations
# is listenup_owner's place: it owns every schema and table.
# Creating a BYPASSRLS role needs a superuser; on a managed database where the
# migration role is not one, an administrator runs this block once beforehand.
ROLES = """
-- Roles and their settings are shared by every database on the server, so two
-- databases migrating at the same moment (parallel test runs, several environments
-- on one server) race on them and PostgreSQL refuses one with "tuple concurrently
-- updated". The work is idempotent, so a refused attempt waits briefly and retries.
DO $$
DECLARE
  attempt int;
BEGIN
  FOR attempt IN 1..20 LOOP
    BEGIN
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'listenup_api') THEN
        CREATE ROLE listenup_api NOLOGIN;
      END IF;
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'listenup_worker') THEN
        CREATE ROLE listenup_worker NOLOGIN BYPASSRLS;  -- jobs act for many learners
      END IF;
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'listenup_readonly') THEN
        CREATE ROLE listenup_readonly NOLOGIN;
      END IF;

      -- Timeouts per role (Database Design 12.3).
      ALTER ROLE listenup_api SET statement_timeout = '5s';
      ALTER ROLE listenup_api SET idle_in_transaction_session_timeout = '30s';
      ALTER ROLE listenup_worker SET statement_timeout = '60s';
      ALTER ROLE listenup_worker SET idle_in_transaction_session_timeout = '30s';
      ALTER ROLE listenup_readonly SET statement_timeout = '30s';
      ALTER ROLE listenup_readonly SET idle_in_transaction_session_timeout = '30s';
      RETURN;
    EXCEPTION WHEN internal_error OR unique_violation OR duplicate_object THEN
      IF attempt = 20 THEN
        RAISE;
      END IF;
      PERFORM pg_sleep(0.05 * attempt);
    END;
  END LOOP;
END $$;
"""

UPGRADE = f"""
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS btree_gist;

DO $$ BEGIN
  EXECUTE format('ALTER DATABASE %I SET timezone TO %L', current_database(), 'UTC');
END $$;

-- Shared trigger: keep updated_at current on every mutable table.
CREATE FUNCTION public.touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;

CREATE SCHEMA identity;
CREATE SCHEMA content;
CREATE SCHEMA practice;
CREATE SCHEMA grading;
CREATE SCHEMA ai;
CREATE SCHEMA ops;

GRANT USAGE ON SCHEMA {SCHEMAS} TO listenup_api, listenup_worker;
GRANT USAGE ON SCHEMA content, grading, ai, ops TO listenup_readonly;
-- Workers read and write every application table, including ones added later.
-- The API and read-only roles get explicit grants per table, so a new table is
-- closed to them until its migration opens it.
ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMAS}
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO listenup_worker;

CREATE TABLE identity.users (
  id                uuid PRIMARY KEY,
  email             citext NOT NULL UNIQUE CHECK (char_length(email) <= 254),
  password_hash     text,                       -- Argon2id; NULL for Google-only accounts
  display_name      text CHECK (char_length(display_name) <= 80),
  email_verified_at timestamptz,
  status            text NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'pending_deletion', 'deleting')),
  deletion_scheduled_at timestamptz,          -- end of the 7-day grace period (DR-1)
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  CHECK ((status = 'pending_deletion') = (deletion_scheduled_at IS NOT NULL))
);
CREATE INDEX users_deletion_due_idx ON identity.users (deletion_scheduled_at)
  WHERE status = 'pending_deletion';
CREATE TRIGGER users_touch BEFORE UPDATE ON identity.users
  FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

CREATE TABLE identity.auth_sessions (
  id           uuid PRIMARY KEY,
  user_id      uuid NOT NULL REFERENCES identity.users ON DELETE CASCADE,
  token_hash   bytea NOT NULL UNIQUE,           -- SHA-256 of the cookie value
  created_at   timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  user_agent   text CHECK (char_length(user_agent) <= 400),
  ip           inet
);
CREATE INDEX auth_sessions_user_idx    ON identity.auth_sessions (user_id);
CREATE INDEX auth_sessions_expires_idx ON identity.auth_sessions (expires_at);

-- Users are found by email at sign-in, before any learner is known, so the table has
-- no row-level policy; login sessions do.
GRANT SELECT, INSERT, UPDATE, DELETE ON identity.users, identity.auth_sessions TO listenup_api;
{enable_own_rows("identity.auth_sessions")}

-- A request arrives with only its cookie, so the API cannot see its own login session
-- through row-level security yet. This function returns the learner for a live token
-- hash and nothing else; the API then sets app.user_id for the rest of the request.
CREATE FUNCTION identity.resolve_auth_session(p_token_hash bytea) RETURNS uuid
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
  SELECT user_id FROM identity.auth_sessions
   WHERE token_hash = p_token_hash AND expires_at > now()
$$;
REVOKE EXECUTE ON FUNCTION identity.resolve_auth_session(bytea) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION identity.resolve_auth_session(bytea) TO listenup_api;
"""

DOWNGRADE = f"""
{disable_own_rows("identity.auth_sessions")}
ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMAS}
  REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM listenup_worker;
DROP SCHEMA identity, content, practice, grading, ai, ops CASCADE;
DROP FUNCTION public.touch_updated_at();
DO $$ BEGIN
  EXECUTE format('ALTER DATABASE %I RESET timezone', current_database());
END $$;
DROP EXTENSION IF EXISTS btree_gist;
DROP EXTENSION IF EXISTS citext;
"""


def upgrade() -> None:
    op.execute(ROLES)
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
