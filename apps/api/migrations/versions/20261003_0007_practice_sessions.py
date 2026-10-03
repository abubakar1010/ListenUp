"""Practice sessions and their steps, with the step-order and entry-lock triggers.

Implements the session state machine story (#47): Database Design 5, 8.1, 8.2 and 9.2;
FR-PL-2, FR-PL-4, FR-PL-5, FR-PL-7, C2 and NFR-SEC-2. The rules in
`modules/practice/domain/plan.py` are the source of truth; the database repeats the
ones that can be checked from stored data alone, so a bug or a manual fix cannot
break them.

Refinements of the design, covered by tests/integration/test_practice_schema.py:
- session_steps references sessions only through the composite (session_id, user_id)
  key, so a step always belongs to the session's learner; the design's extra
  single-column reference would add nothing.
- sessions_passage_bounded refuses empty, unbounded and negative passages, which
  the length CHECK lets through because it compares NULLs.
- session_steps_order also fires on INSERT: a rebuilt plan (a changed entry choice)
  inserts its steps, and an inserted 'open' step must obey the same order.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op

from migrations.rls import disable_own_rows, enable_own_rows

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = f"""
-- A session always practises the learner's own content item: the pair (content id,
-- learner) is referenced together, as every child row does with its session.
ALTER TABLE content.contents ADD CONSTRAINT contents_id_user_uq UNIQUE (id, user_id);

CREATE TABLE practice.sessions (
  id              uuid PRIMARY KEY,
  user_id         uuid NOT NULL REFERENCES identity.users ON DELETE CASCADE,
  content_id      uuid NOT NULL,
  passage         int4range NOT NULL
                  CHECK (upper(passage) - lower(passage) BETWEEN 30000 AND 900000),
  entry           text NOT NULL CHECK (entry IN ('blind', 'dictation', 'both')),
  current_step    text NOT NULL
                  CHECK (current_step IN ('blind', 'dictation', 'transcript', 'card', 'shadow',
                                          'done')),
  entry_locked_at timestamptz,             -- set when Transcript opens (FR-PL-5)
  status          text NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active', 'completed', 'abandoned')),
  version         int4 NOT NULL DEFAULT 0, -- optimistic concurrency
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  completed_at    timestamptz,
  -- upper() and lower() are NULL for an empty or unbounded range, which would pass
  -- the length CHECK above.
  CONSTRAINT sessions_passage_bounded CHECK (NOT isempty(passage) AND NOT lower_inf(passage)
    AND NOT upper_inf(passage) AND lower(passage) >= 0),
  CONSTRAINT sessions_id_user_uq UNIQUE (id, user_id),
  CONSTRAINT sessions_content_user_fk FOREIGN KEY (content_id, user_id)
    REFERENCES content.contents (id, user_id) ON DELETE CASCADE
);
CREATE INDEX sessions_user_idx    ON practice.sessions (user_id, updated_at DESC, id);
CREATE INDEX sessions_content_idx ON practice.sessions (content_id);
CREATE TRIGGER sessions_touch BEFORE UPDATE ON practice.sessions
  FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

CREATE TABLE practice.session_steps (
  session_id   uuid NOT NULL,
  user_id      uuid NOT NULL,
  step         text NOT NULL CHECK (step IN ('blind', 'dictation', 'transcript', 'card', 'shadow')),
  position     int2 NOT NULL CHECK (position BETWEEN 1 AND 5),
  status       text NOT NULL CHECK (status IN ('locked', 'open', 'done', 'skipped')),
  opened_at    timestamptz,
  completed_at timestamptz,
  PRIMARY KEY (session_id, step),
  UNIQUE (session_id, position),
  CHECK (status <> 'skipped' OR step IN ('card', 'shadow')),  -- FR-PL-7
  CONSTRAINT session_steps_session_user_fk FOREIGN KEY (session_id, user_id)
    REFERENCES practice.sessions (id, user_id) ON DELETE CASCADE
);

-- A step may open only when the step before it is done or skipped (FR-PL-4).
CREATE FUNCTION practice.check_step_order() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status = 'open' AND NEW.position > 1 AND NOT EXISTS (
       SELECT 1 FROM practice.session_steps
       WHERE session_id = NEW.session_id AND position = NEW.position - 1
         AND status IN ('done', 'skipped')) THEN
    RAISE EXCEPTION 'step_locked: % cannot open before step %', NEW.step, NEW.position - 1
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER session_steps_order BEFORE INSERT OR UPDATE OF status ON practice.session_steps
  FOR EACH ROW EXECUTE FUNCTION practice.check_step_order();

-- The entry choice is frozen once Transcript has opened (FR-PL-5).
CREATE FUNCTION practice.check_entry_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.entry_locked_at IS NOT NULL AND NEW.entry IS DISTINCT FROM OLD.entry THEN
    RAISE EXCEPTION 'entry_locked' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER sessions_entry_lock BEFORE UPDATE OF entry ON practice.sessions
  FOR EACH ROW EXECUTE FUNCTION practice.check_entry_lock();

GRANT SELECT, INSERT, UPDATE, DELETE ON practice.sessions, practice.session_steps
  TO listenup_api;
{enable_own_rows("practice.sessions")}
{enable_own_rows("practice.session_steps")}
"""

DOWNGRADE = f"""
{disable_own_rows("practice.session_steps")}
{disable_own_rows("practice.sessions")}
DROP TABLE practice.session_steps;
DROP FUNCTION practice.check_step_order();
DROP TABLE practice.sessions;
DROP FUNCTION practice.check_entry_lock();
ALTER TABLE content.contents DROP CONSTRAINT contents_id_user_uq;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
