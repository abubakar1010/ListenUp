# ADR 0058: Card source times and slot allocation

- Status: Accepted
- Date: 2026-10-23

## Context

Story #72 saves a connected-speech card from a mark. Marks can be removed later,
while saved cards must keep their source time. Database Design §5 already makes
`mark_id` nullable on deletion and reserves two unique slots per session (D14).
Audio snippet generation belongs to #73.

## Decision

- Add an `at_ms` snapshot of the selected mark's absolute time to `practice.cards`.
  The server obtains it only through `review.service.list_marks`; clients cannot
  submit or replace the source time. Cards link to their session's content at that
  time. Removing a mark clears `mark_id` and keeps the saved card and source time.
- Keep the designed nullable snippet columns, unused until #73. Do not expose a
  snippet playback endpoint in #72.
- Creation locks the learner-scoped session row, then rechecks `Step.CARD` and
  chooses the lowest available slot. Completion takes the same lock. The database
  independently enforces `slot IN (1, 2)` and `UNIQUE (session_id, slot)`; concurrent
  attempts for the last slot produce one card and one `card_limit_reached` refusal.
- Use the existing request transaction, submission idempotency, learner RLS,
  composite session ownership FK, explicit API grants, analytics and export hooks.
  Card deletion frees a live slot, including when the Card step is still open.

## Consequences

A card remains useful after its mark is removed. Source-time navigation adds only
an optional `at_ms` query parameter to the content player. Creates for a session
serialize briefly; other sessions remain independent. Skip transitions keep their
existing practice service concurrency rules. No review internals or audio jobs
change.
