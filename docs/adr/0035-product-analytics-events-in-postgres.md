# ADR 0035: Product analytics as server-side events in PostgreSQL, reported by a read-only script

- Status: Accepted
- Date: 2026-10-05
- Source: issue #101; [PRD 2 (success metrics) and 8.2 (analytics events)](../design/prd.md); [SRS 9.3 (OI-3), DR-1, NFR-SEC-5](../design/srs.md); ADRs 0013, 0014, 0021 and 0030

## Context

The beta has to show whether learners finish plans and whether repeat failures fall (PRD 2). PRD 8.2 lists the events to track: content added (source type), plan started (path), step started, step completed, Dictation replay count, Blind abandoned, marks created, cards created and Shadow rounds completed. The Database Design defines no analytics table. Third-party analytics SDKs are out of scope, events may carry no personal data beyond a pseudonymous learner id, and they must disappear when an account is purged (DR-1, #91).

## Decision

### One table, written in the transaction of the change

`ops.analytics_events` (migration 0015) holds one row per event: `user_id`, `event_type`, `subject_id` (what the event is about: the content item, session, attempt, mark, card or Shadow round), `step` (step events only), `content_id`, `session_id`, `properties` (small typed values) and `occurred_at`.

Events are recorded on the server by the module that makes the change, inside its request transaction, through `modules/analytics/service.py` (one call per site). An event therefore commits or rolls back with the change it describes, and a refused request leaves none. The one browser signal is Dictation's first media `playing` event, because only the browser can distinguish opening its player from actually starting playback; its authenticated endpoint writes the event server-side and is idempotent. A `play` request that buffers, fails or is paused before playback begins records nothing.

### Once per occurrence

The unique key `analytics_events_once (event_type, subject_id, step)`, with `NULLS NOT DISTINCT`, and `INSERT ... ON CONFLICT DO NOTHING` on every write make each occurrence count once. A retried request, an `Idempotency-Key` replay, a re-confirmed upload, a repeated Blind void or a resumed Dictation attempt records nothing new. A step reopened by an entry change counts as started once per session.

### What each event means

- `content_added {source_type}`: `Uploads.confirm` created a new item (YouTube intake will make the same call).
- `plan_started {path}`: `practice.start_session`.
- `step_started` and `step_completed {outcome: done | skipped}`: derived in `practice` from the plan's step statuses before and after every transition (`analytics.domain.step_changes`). A step starts when the plan moves onto it (the first step at plan start, then each step that opens). This works for all five steps today, and gives "reached Transcript" and "reached the final step" directly. "First action in the step" would need features that Transcript, Card and Shadow do not have yet.
- `listen_started {mode}`: playback began. For Blind, the learner's explicit Start action creates the attempt and event. For Dictation, opening the screen creates or resumes the attempt but records nothing; the first media `playing` event calls `POST /dictation/attempts/{id}/listen`. The unique event key makes retries and later plays harmless.
- `blind_abandoned {reason}`: a Blind attempt was voided (`blind._void`, both heartbeat and browser-reported voids). Starting an attempt also queues a delayed background check. While the first resume remains available, silence becomes final only at five minutes after the last accepted heartbeat (ADR 0024). After that resume is used, expiry uses the existing 15-second silence limit. The worker follows the current deadline and voids only incomplete active attempts with `missed_heartbeat`, so a vanished browser is recorded without removing its eligible recovery.
- `dictation_replays {replay_count}`, `mark_created {pattern}`, `card_created`, `shadow_round_completed {round}`: their recording functions exist and are tested, but nothing calls them yet. Replays are counted only in the browser, and Dictation submission (#53) will send the count; marks, cards and Shadow do not exist yet. They fire once those features call them; none are faked.

### Privacy

- No email, name, IP address, user agent, title, transcript or typed text. A mark is stored only as an HMAC of its normalised phrase, keyed with a dedicated service secret and scoped by learner id (`pattern`). The report can compare one learner's failures but cannot dictionary-match common phrases or correlate the same phrase across learners. `LISTENUP_ANALYTICS_HMAC_KEY` must be stable and non-default outside local and test environments.
- `user_id` is the account's random id, which is pseudonymous: the events table alone does not name anyone.
- `user_id` references `identity.users ON DELETE CASCADE`. The purge in #91 ends with `DELETE FROM identity.users`, so the learner's events go with the account without any change to the purge, and its catalog-based purge report counts them. Anonymising instead (keeping rows with the id removed) was rejected: DR-1 says deletion removes all of the learner's data, and the metrics do not need a deleted learner's history.
- `content_id` and `session_id` have no foreign key. Deleting a clip or a session keeps its events: they hold no content, the ids then point to nothing, and later deletions do not rewrite past metrics. This is an explicit owner-approved exception to DR-2 and AT-9 (2026-10-15), now recorded in the SRS and Database Design. Events remain in learner exports and are removed on account deletion; this implementation has no separate age-based expiry.
- Because `user_id` is the account id rather than a separate pseudonym, the events are the learner's data: `analytics.service.export_data` adds them to the data export (NFR-SEC-5, ADR 0030), and `test_export.py` covers them.

### Access

- `listenup_api` has `INSERT` only, under the `own_rows` policy, so a request writes only its learner's events and cannot read any back. `ON CONFLICT DO NOTHING` needs no read access.
- `listenup_readonly` has `SELECT` and a read-only policy `analytics_report` over every row. That role cannot read the `identity` schema, so whoever runs the report sees pseudonymous ids and never an email.
- The workers' role reads the events for the export through its default grants.
- The analytics module imports no other module (an import-linter contract), so every module can call it without an import cycle.

### The report

There is no admin role or admin page yet, and adding one would touch identity. The report is therefore a script, run as `listenup_readonly` in a read-only transaction:

    uv run python scripts/analytics_report.py --from 2026-09-01 --to 2026-09-30 [--json]

The metric definitions are pure functions in `analytics/domain/metrics.py`. A cohort is chosen by when it started in the range, and follow-ups count up to `--as-of` (default now). The report refuses a range whose end is after `--as-of`, rather than labelling a partial cohort as a complete range:

- **Plan completion rate**: of the plans started in the range, how many reached the final step (Shadow started, the PRD's definition) and how many completed it (Shadow done or skipped, SH-6).
- **Time to first listen**: for clips added in the range, the time from `content_added` to the first `listen_started` on the clip, as median, 90th percentile and share under 60 s.
- **Return rate**: learners whose first plan started in the range and who started 3 or more plans within 14 days of it. Learners still inside their 14 days who have not yet returned are reported apart and left out of the rate.
- **Mark reuse**: cards plus Shadow segments (sessions with a Shadow round) per session that reached Transcript in the range. "No data" until card or Shadow events exist.
- **Repeat-failure trend**: the share of marks in the range whose pattern the learner marked in an earlier session, by session number 1 to 8. "No data" until marks exist.

The script reads every event before `--as-of` and computes in Python. Beta volumes are small. Aggregating in SQL is the next step when volumes grow.

## Consequences

- Marks, cards, Shadow rounds and Dictation submission must call their recording functions when they are built. Until then, mark reuse and the repeat-failure trend report "no data", and no replay counts exist.
- The first plan seen for a learner counts as their first, so learners active before migration 0015 look new in the first return-rate reports.
- A new event type needs a migration (the `event_type` CHECK) and a recording function in `analytics/service.py`.
- Migration 0015 is chained to the current head of `main` (0012). #131 adds 0013 on the same head, so whichever merges second re-chains onto the other; the single-head migration test fails until it does. #130 adds no migration.
- Recording never fails the learner's action: each `record_*` runs in a savepoint, and a value analytics does not know, or a row the table refuses, is logged and dropped. The cost is a silently missing event, so a new step, entry or source type must be added to `analytics.domain` and the CHECKs in the same change.
- The analytics HMAC key is a deployment secret shared by API instances. Rotating it starts a new pattern namespace and therefore needs an explicit migration/versioning decision; accidental use of the local default is refused outside local and test environments.
- Marks from sessions that started before migration 0015 have no `plan_started` event. The repeat-failure trend counts them in its totals but gives them no session number.
- The Database Design records the table, grants, reporting policy, account deletion and export behavior. The owner approved retention after clip/session deletion as an explicit exception to DR-2 and AT-9; all documents now state the same policy.
