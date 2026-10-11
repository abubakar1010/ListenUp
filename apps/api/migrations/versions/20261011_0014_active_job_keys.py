"""Enforce unique job keys while queued or running (ADR 0034).

The library's queueing-lock index covers only waiting jobs. Application existence
checks race concurrent inserts and worker starts. Keep the library index and add
an active-key index; postponed runs atomically hand their key to their successor.
Deploy with workers stopped. If legacy duplicates exist, the index build refuses
the migration rather than dropping work: settle them before retrying the upgrade.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
    CREATE UNIQUE INDEX procrastinate_jobs_active_key_idx
      ON procrastinate.procrastinate_jobs (queueing_lock)
      WHERE status IN ('todo', 'doing');
    """)


def downgrade() -> None:
    op.execute("DROP INDEX procrastinate.procrastinate_jobs_active_key_idx")
