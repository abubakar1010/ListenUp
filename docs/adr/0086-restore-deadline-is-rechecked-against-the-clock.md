# ADR 0086: The restore deadline is rechecked against the clock during sign-in

- Status: Accepted
- Date: 2026-10-28
- Story: [#228](https://github.com/abubakar1010/ListenUp/issues/228) item 5 (owner decision E3)
- Requirements: FR-ACC-4, DR-1; ADR 0029 (grace period and restore), ADR 0039 (Google sign-in and deletion confirmation)

## Context

ADR 0029 allows a restore only while `deletion_scheduled_at > now()`. In PostgreSQL `now()` is the start of the transaction, and the sign-in request's transaction starts before the Argon2 check, which can take a noticeable time. The account was looked up before that check, so a grace period that ended meanwhile was still treated as open: the learner could be offered a restore (409 `account_pending_deletion`) or granted one, up to the length of the request after the deadline.

## Decision

- `Accounts.complete_sign_in` (the one place every sign-in method ends, so Google sign-in inherits it) asks the database again, with `clock_timestamp()`, whether the grace period is still open before offering a restore. An explicit Restore uses the locked recheck below. Expiry answers the normal `invalid_credentials` response, with or without `restore`; password sign-in preserves the unknown-address failure counter and response fields without another hash check.
- `restore_account` takes the users-row lock explicitly, after the deletion-request lock, then compares `deletion_scheduled_at` with `clock_timestamp()` in its `UPDATE`. A locking transaction need not modify the tuple, so a predicate evaluated before the lock wait is not a reliable check of time after that wait. The explicit lock makes the ordering unconditional. A false result keeps its existing meaning and answer; cancellation of the deletion request rolls back.
- The `_GONE` predicate used by lookups keeps `now()`: a lookup runs at the start of the request, and the two rechecks above close the gap.

## Consequences

- A restore that races the deadline is refused rather than granted late; a restore cannot be granted for an account the purge may already be taking.
- No schema change. Tests: `test_restore_offer_rechecks_deadline_after_password_verification`, `test_restore_grant_rechecks_deadline_after_user_lock`, and `test_restore_deadline_exact_boundary_is_expired` (offer and grant). They compare the complete refusal body with an unknown account and assert no restoration or session. The row-lock test uses an event rather than a timed delay.
