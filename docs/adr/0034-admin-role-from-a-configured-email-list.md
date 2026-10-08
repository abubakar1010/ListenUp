# ADR 0034: Administrators from a configured email list; failed jobs retried as new jobs

- Status: Accepted
- Date: 2026-10-08
- Source: issue #100; [SRS 2.2 (Administrator), NFR-AI-10](https://claude.ai/code/artifact/fd47a9cb-6515-4fde-a232-3ab8cc14f0dd); [Software Architecture 4.1 (admin) and 9.2 (Admin: `GET /admin/usage`, `GET /admin/jobs`)](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13); [System Design 11.1 (failed jobs visible to an admin)](https://claude.ai/code/artifact/98274889-96ba-4424-afad-c2cd056206e2); ADRs 0013, 0014 and 0015

## Context

Administrators watch the job queue and, later, AI usage against free quotas (NFR-AI-10), without access to learner media or text by default (SRS 2.2). The design names the admin routes but not how an account becomes an admin. Issue #100 asks for a configuration list of admin emails for the MVP. This decision covers the role and the job view; the usage view follows once the `ai.calls` and `ai.quota_usage` tables exist (#64).

Two constraints shape it. Anyone can register an account with any email, and no email verification flow exists yet. The API connects as `listenup_api`, which may insert into Procrastinate's tables but not update them (migration 0003), and Procrastinate's own retry moves a failed job back to `todo` with an UPDATE.

## Decision

### Who is an admin

- `LISTENUP_ADMIN_EMAILS` holds a comma-separated list of emails; empty (the default) means nobody is an admin. An account is an admin when its email is in the list, compared without case or surrounding spaces, **and its address is verified** (`identity.users.email_verified_at` is set). The rule is the pure `is_admin` in `modules/admin/domain/roles.py`.
- The verified address is required because registration does not check ownership: without it, anyone could register a listed address that its owner had not signed up with yet and become an admin. Until email verification (or Google sign-in, ADR 0006) sets the flag, the operator marks the admin's own account verified once, as the database owner: `UPDATE identity.users SET email_verified_at = now() WHERE email = '<admin email>';`.
- The admin module reads the signed-in learner's email through `identity.service.get_profile`, so identity is unchanged. There is no role table and no migration; changing the list takes a restart.

### What everyone else gets

- Every admin route takes `CurrentAdmin` (`modules/admin/service.py`). A signed-in learner who is not an admin gets 404 `not_found` with the same detail as a path that does not exist, so a learner cannot tell the routes are there. Signed out, the routes answer 401 `not_signed_in` like every other protected route (the cross-learner access test, #34, requires it of every route).
- `tests/integration/access_registry.py` has an `Admin` entry kind: learners A and B both get 404 `not_found`, and nothing of A's changes.
- Admin answers carry counts, job ids, lanes, task names, attempt counts and times. Job arguments are never returned: they hold learner ids, storage keys and sometimes text.

### The job view and retry

- `GET /admin/jobs` returns every lane in priority order with jobs waiting (due now), scheduled (a retry's backoff or a postponed start), running, and how long the longest-waiting due job has waited; and the 50 newest failed jobs not yet retried (`platform.jobs.failed_jobs`).
- `POST /admin/jobs/{id}/retry` (202, `{"job_id": <new id>}`) queues a failed job again through `platform.jobs.retry_failed_job`: a **new** job with the same task, lane, priority, lock, unique key and arguments, and a fresh set of attempts. The failed job stays as it was, for the record, and gets Procrastinate's own `retried` event; a failed job whose last `failed` event is followed by a `retried` one leaves the failed list. That also holds for a job retried with Procrastinate's own tools.
- A second retry of the same job answers 404 `job_not_found`; concurrent retries of one job are serialised by an advisory lock. When a job with the same unique key is already waiting, the retry answers 409 `job_already_queued` and the failed job stays listed.
- A retry is idempotent by itself (the second one is refused), so it takes no `Idempotency-Key`.

## Consequences

- No migration and no new grant: the API role only inserts a job and an event, as it already does when it queues work.
- The admin's account needs one manual step until email verification exists. A listed address that is not verified is simply not an admin.
- A retried job starts with fresh attempts and backoff, rather than Procrastinate's single extra attempt. Handlers are idempotent (ADR 0015), so running one again is safe; a job whose `on_give_up` marked an item failed runs its handler again, which may move the item on.
- The job view reads Procrastinate's tables as `listenup_api`. The `listenup_readonly` role the issue mentions has no login and the API is not a member of it; reading as that role would need a grant in a migration. The usage view (#64) can revisit this when it reads the non-personal `ai` tables.
- Changing who is an admin is a configuration change and a restart, which suits a handful of operators. A role column or table can replace the list later without changing the routes.
