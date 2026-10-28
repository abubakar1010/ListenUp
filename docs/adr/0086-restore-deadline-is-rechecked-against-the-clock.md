# ADR 0086: The restore deadline is rechecked against the clock during sign-in

- Status: Accepted
- Date: 2026-10-28
- Story: [#228](https://github.com/abubakar1010/ListenUp/issues/228) item 5 (owner decision E3)
- Requirements: FR-ACC-4, DR-1; ADR 0029 (grace period and restore), ADR 0039 (Google sign-in and deletion confirmation)

## Context

ADR 0029 allows a restore only while `deletion_scheduled_at > now()`. In PostgreSQL `now()` is the start of the transaction, and the sign-in request's transaction starts before the Argon2 check, which can take a noticeable time. The account was looked up before that check, so a grace period that ended meanwhile was still treated as open: the learner could be offered a restore (409 `account_pending_deletion`) or granted one, up to the length of the request after the deadline.

## Decision

- `Accounts.complete_sign_in` (the one place every sign-in method ends, so Google sign-in inherits it) asks the database again, with `clock_timestamp()`, whether the grace period has ended, before it offers or grants a restore. If it has, the answer is the normal 401 `invalid_credentials`, with or without `restore`.
- `restore_account` compares `deletion_scheduled_at` with `clock_timestamp()` in its `UPDATE`. The `UPDATE` takes the row lock itself; if another transaction (the purge, a deletion) holds the row, PostgreSQL waits for it and then evaluates the `WHERE` clause again on the committed row, so the deadline is read after any wait for the lock. A separate `SELECT ... FOR UPDATE` first would add nothing and is not used. A false result keeps its existing meaning and answer.
- The `_GONE` predicate used by lookups keeps `now()`: a lookup runs at the start of the request, and the two rechecks above close the gap.

## Consequences

- A restore that races the deadline is refused rather than granted late; a restore cannot be granted for an account the purge may already be taking.
- No schema change. Tests: `test_a_grace_period_that_ends_during_password_verification_is_refused` and `test_a_grace_period_that_ends_before_the_restore_locks_the_account_is_refused` and `test_a_restore_that_waits_for_the_row_lock_is_refused_when_the_period_ends_meanwhile`.
