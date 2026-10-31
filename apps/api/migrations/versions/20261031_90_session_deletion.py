"""A learner deletes one practice session: barrier and one open request (#90, ADR 0092)."""

from alembic import op

revision = "90_session_deletion"
down_revision = "93_shadow_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The API already holds UPDATE on practice.sessions (migration 0007).
    op.execute("""
ALTER TABLE practice.sessions ADD COLUMN deleting_at timestamptz;
CREATE UNIQUE INDEX deletion_requests_one_open_session_idx
 ON ops.deletion_requests(subject_user_id,target_id)
 WHERE scope='session' AND status IN ('pending','storage_deleted','failed');
""")


def downgrade() -> None:
    # Open session requests stay in ops.deletion_requests; after upgrading again the
    # reconciler resumes them and the job hides each session again (ADR 0092).
    op.execute("""
DROP INDEX ops.deletion_requests_one_open_session_idx;
ALTER TABLE practice.sessions DROP COLUMN deleting_at;
""")
