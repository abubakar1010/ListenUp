"""Idempotency keys and rate counters.

Platform tables used by every endpoint that accepts an Idempotency-Key or is rate
limited (Architecture 9.1; Database Design 7). Part of the platform package story
(#25).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op

from migrations.rls import disable_own_rows, enable_own_rows

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = f"""
-- Fixed-window rate limits. UNLOGGED: fast, and losing counts on a crash is harmless.
-- Keys: 'login:ip:<ip>', 'login_fail:user:<id>', 'login_lock:user:<id>', 'intake:user:<id>'.
CREATE UNLOGGED TABLE ops.rate_counters (
  key          text NOT NULL CHECK (char_length(key) <= 200),
  window_start timestamptz NOT NULL,
  count        int4 NOT NULL DEFAULT 0,
  PRIMARY KEY (key, window_start)
);
CREATE INDEX rate_counters_window_idx ON ops.rate_counters (window_start);

CREATE TABLE ops.idempotency_keys (
  user_id      uuid NOT NULL REFERENCES identity.users ON DELETE CASCADE,
  key          text NOT NULL CHECK (char_length(key) BETWEEN 1 AND 100),
  request_hash bytea NOT NULL,       -- same key with a different body is rejected
  status_code  int2,                 -- NULL while the first request is still running
  response     jsonb,
  created_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, key)
);
CREATE INDEX idempotency_keys_age_idx ON ops.idempotency_keys (created_at);

-- Rate counters are checked before any learner is known (sign-in by IP), so they have
-- no row-level policy.
GRANT SELECT, INSERT, UPDATE, DELETE ON ops.rate_counters, ops.idempotency_keys
  TO listenup_api;
{enable_own_rows("ops.idempotency_keys")}
"""

DOWNGRADE = f"""
{disable_own_rows("ops.idempotency_keys")}
DROP TABLE ops.idempotency_keys;
DROP TABLE ops.rate_counters;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
