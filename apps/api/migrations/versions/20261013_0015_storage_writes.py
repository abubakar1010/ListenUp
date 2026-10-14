"""Retain storage fences after connection loss (DR-1, ADR 0029).

Deploy with workers stopped. Never expire a writer by age; reconcile abandoned
registrations only after its process and all S3 writes have stopped.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ops.storage_writes (
            id uuid PRIMARY KEY,
            subject_user_id uuid NOT NULL REFERENCES identity.users(id) ON DELETE RESTRICT,
            owner text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX storage_writes_subject_idx ON ops.storage_writes (subject_user_id);
        ALTER TABLE ops.storage_writes ENABLE ROW LEVEL SECURITY;
        GRANT SELECT, INSERT, DELETE ON ops.storage_writes TO listenup_worker;
    """)


def downgrade() -> None:
    # Refuse to drop protection while an upload may still be running.
    op.execute("""
        LOCK TABLE ops.storage_writes IN ACCESS EXCLUSIVE MODE;
        DO $$ BEGIN
            IF EXISTS (SELECT FROM ops.storage_writes) THEN
                RAISE EXCEPTION 'reconcile storage writers before downgrading';
            END IF;
        END $$;
        DROP TABLE ops.storage_writes;
    """)
