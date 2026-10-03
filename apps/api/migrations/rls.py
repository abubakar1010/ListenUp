"""Row-level security helpers for migrations (Database Design 9.2).

Every table with a `user_id` column gets the same `own_rows` policy. The API sets the
learner with `SELECT set_config('app.user_id', '<uuid>', true)` inside each
transaction. When the setting is missing or empty the comparison is NULL, so no rows
are visible and no rows can be written: a forgotten setting fails closed.

NULLIF matters: after a transaction-local set_config ends, the setting reads back as
'' rather than NULL, and ''::uuid would raise an error instead of returning nothing.
"""

CURRENT_LEARNER = "NULLIF(current_setting('app.user_id', true), '')::uuid"


def enable_own_rows(table: str) -> str:
    return f"""
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_rows ON {table}
  USING (user_id = {CURRENT_LEARNER})
  WITH CHECK (user_id = {CURRENT_LEARNER});
"""


def disable_own_rows(table: str) -> str:
    return f"""
DROP POLICY own_rows ON {table};
ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
"""
