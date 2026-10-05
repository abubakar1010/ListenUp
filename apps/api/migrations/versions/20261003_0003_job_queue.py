"""Job queue: Procrastinate's tables in their own `procrastinate` schema.

Part of the job lanes story (#28); Database Design 1.1 and System Design 4. The SQL is
Procrastinate's own schema, vendored at the installed version
(migrations/sql/procrastinate-<version>.sql) so that a database built today and one
built after a library upgrade end up identical. tests/integration/test_jobs.py fails
when the installed Procrastinate ships a different schema: a library upgrade then
needs a new migration that applies Procrastinate's own migration files.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-03
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROCRASTINATE_VERSION = "3.10.0"
SCHEMA_SQL = (
    Path(__file__).resolve().parents[1] / "sql" / f"procrastinate-{PROCRASTINATE_VERSION}.sql"
)

# Procrastinate refers to its objects without a schema name, so every connection
# needs `procrastinate` on its search path. Setting it on the database covers the
# workers, the API (which enqueues jobs in its own transactions) and psql.
SEARCH_PATH = '"$user", public, procrastinate'

GRANTS = """
GRANT USAGE ON SCHEMA procrastinate TO listenup_api, listenup_worker, listenup_readonly;
-- Workers run the queue.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA procrastinate TO listenup_worker;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA procrastinate TO listenup_worker;
-- The API only enqueues (and reads job state for status and the admin view).
GRANT SELECT, INSERT ON procrastinate.procrastinate_jobs, procrastinate.procrastinate_events
  TO listenup_api;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA procrastinate TO listenup_api;
-- Failed jobs are listed for an admin (System Design 11.1).
GRANT SELECT ON procrastinate.procrastinate_jobs, procrastinate.procrastinate_events
  TO listenup_readonly;
"""


# Before this migration, Docker Compose created the queue in `public`. Those copies
# would shadow the new schema on the search path, so they are removed when empty.
REMOVE_OLD_PUBLIC_QUEUE = """
DO $$
DECLARE
  obj record;
BEGIN
  IF to_regclass('public.procrastinate_jobs') IS NULL THEN
    RETURN;
  END IF;
  IF EXISTS (SELECT FROM public.procrastinate_jobs) THEN
    RAISE EXCEPTION 'public.procrastinate_jobs still holds jobs; finish or delete them, '
      'or recreate the local database (docker compose down -v), then migrate again';
  END IF;
  DROP TABLE IF EXISTS public.procrastinate_events, public.procrastinate_periodic_defers,
    public.procrastinate_jobs, public.procrastinate_workers CASCADE;
  FOR obj IN
    SELECT p.oid::regprocedure AS signature FROM pg_proc p
     WHERE p.pronamespace = 'public'::regnamespace AND p.proname LIKE 'procrastinate%'
  LOOP
    EXECUTE format('DROP FUNCTION %s CASCADE', obj.signature);
  END LOOP;
  DROP TYPE IF EXISTS public.procrastinate_job_to_defer_v1, public.procrastinate_job_status,
    public.procrastinate_job_event_type CASCADE;
END $$;
"""


def upgrade() -> None:
    op.execute(REMOVE_OLD_PUBLIC_QUEUE)
    op.execute("CREATE SCHEMA procrastinate")
    op.execute("SET LOCAL search_path TO procrastinate, public")
    op.execute(SCHEMA_SQL.read_text())
    op.execute(GRANTS)
    op.execute(f"""
    DO $$ BEGIN
      EXECUTE format('ALTER DATABASE %I SET search_path TO {SEARCH_PATH}', current_database());
    END $$;
    """)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      EXECUTE format('ALTER DATABASE %I RESET search_path', current_database());
    END $$;
    """)
    op.execute("DROP SCHEMA procrastinate CASCADE")
