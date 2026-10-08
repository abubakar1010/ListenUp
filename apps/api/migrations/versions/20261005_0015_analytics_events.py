"""Product analytics events (#101, PRD 2 and 8.2, ADR 0033).

`ops.analytics_events` holds one row per product event, written by the API in the
same transaction as the change it describes, so a refused or rolled-back request
leaves no event.

- Once per occurrence: `analytics_events_once` makes (event type, subject, step)
  unique, and every insert is `ON CONFLICT DO NOTHING`, so a retried request, a
  repeated void or a resumed attempt records nothing new. `subject_id` is what the
  event is about (the content item, session, attempt, mark, card or Shadow round);
  `step` is set only on step events.
- No personal data beyond the learner's id: no email, name, address, title or typed
  text. `properties` holds small typed values (source type, path, outcome, reason,
  counts, a hash of a mark's phrase).
- `user_id` cascades from `identity.users`, so the account purge (#91) removes the
  learner's events. `content_id` and `session_id` have no foreign key: deleting a clip
  or session keeps its events, which then point to nothing and hold no content.
- The API may only insert (its own rows, under `own_rows`). The report runs as
  `listenup_readonly`, which may read every learner's events (`analytics_report`) but
  not `identity`, so it sees pseudonymous ids only. The export job (workers' role)
  reads them through the default grants.

Revision ID: 0015
Revises: 0012. #131 (0013, account deletion) also revises 0012: whichever pull request
merges second must set its `down_revision` to the other's revision before merging;
`tests/integration/test_migrations.py` fails on two heads until it does.
Create Date: 2026-10-05
"""

from collections.abc import Sequence

from alembic import op

from migrations.rls import disable_own_rows, enable_own_rows

revision: str = "0015"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = f"""
CREATE TABLE ops.analytics_events (
  id          uuid PRIMARY KEY,
  user_id     uuid NOT NULL REFERENCES identity.users ON DELETE CASCADE,
  event_type  text NOT NULL
              CHECK (event_type IN ('content_added', 'plan_started', 'step_started',
                                    'step_completed', 'listen_started', 'dictation_replays',
                                    'blind_abandoned', 'mark_created', 'card_created',
                                    'shadow_round_completed')),
  subject_id  uuid NOT NULL,
  step        text CHECK (step IN ('blind', 'dictation', 'transcript', 'card', 'shadow')),
  content_id  uuid,   -- no foreign key: the event outlives a deleted clip
  session_id  uuid,   -- no foreign key: the event outlives a deleted session
  properties  jsonb NOT NULL DEFAULT '{{}}'
              CHECK (jsonb_typeof(properties) = 'object' AND pg_column_size(properties) <= 1000),
  occurred_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT analytics_events_step_events_have_a_step
    CHECK ((step IS NOT NULL) = (event_type IN ('step_started', 'step_completed'))),
  CONSTRAINT analytics_events_once UNIQUE NULLS NOT DISTINCT (event_type, subject_id, step)
);
CREATE INDEX analytics_events_type_time_idx ON ops.analytics_events (event_type, occurred_at);
CREATE INDEX analytics_events_user_idx ON ops.analytics_events (user_id, occurred_at);

GRANT INSERT ON ops.analytics_events TO listenup_api;
GRANT SELECT ON ops.analytics_events TO listenup_readonly;
{enable_own_rows("ops.analytics_events")}
CREATE POLICY analytics_report ON ops.analytics_events FOR SELECT TO listenup_readonly
  USING (true);
"""

DOWNGRADE = f"""
DROP POLICY analytics_report ON ops.analytics_events;
{disable_own_rows("ops.analytics_events")}
DROP TABLE ops.analytics_events;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
