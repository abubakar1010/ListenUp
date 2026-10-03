# ADR 0013: SQL migrations with row-level security from the first table

- Status: Accepted
- Date: 2026-10-03

## Context

The Database Design keeps product rules and learner isolation in PostgreSQL itself: CHECK constraints, triggers, an exclusion constraint and row-level security (sections 8 and 9). Alembic's autogenerate cannot express most of these, and the design also asks CI to detect drift with `alembic check` (section 12.2). Building the baseline (#27) showed three gaps in the design as written:

- `identity.auth_sessions` is under row-level security, but a request arrives with only its cookie, so the API cannot find its own login session before it knows the learner.
- After a transaction-local `set_config('app.user_id', ..., true)` ends, the setting reads back as `''`, not NULL, and `''::uuid` raises an error instead of returning no rows.
- PostgreSQL roles belong to the whole server, and creating a `BYPASSRLS` role needs a superuser.

## Decision

- Migrations are hand-written SQL run through `op.execute`, one Alembic revision per story. SQLAlchemy models mirror each table only so that `alembic check` reports drift between the code and the schema.
- Every table with a `user_id` gets the `own_rows` policy from `migrations/rls.py`, which compares against `NULLIF(current_setting('app.user_id', true), '')::uuid`, so a missing or empty setting returns no rows and allows no writes.
- `identity.resolve_auth_session(token_hash)` is a `SECURITY DEFINER` function, executable only by `listenup_api`, that returns the learner of a live login session and nothing else. The API calls it first, then sets `app.user_id`.
- The baseline creates `listenup_api`, `listenup_worker` (`BYPASSRLS`) and `listenup_readonly` as NOLOGIN roles when they are missing, with their timeouts, and never drops them. Each environment enables login with a password from its secrets. The role that runs migrations is the owner (`listenup_owner` in the design). On a managed database whose migration role is not a superuser, an administrator creates the roles once beforehand.
- Workers get read and write rights on every application table through default privileges. The API and read-only roles get explicit grants per table, so a new table stays closed to them until its migration opens it.

## Consequences

Feature stories add their tables, constraints, policies and grants in new revisions, plus a model for each table. Integration tests run against a real PostgreSQL 16 server and try to break each rule; CI fails rather than skips them when the database is missing. Procrastinate still creates its own tables in `public`, outside Alembic; the grants that let the API and worker roles use the queue come with the first feature that enqueues jobs under those roles. (Superseded on this point by ADR 0015: migration 0003 creates the queue in its own `procrastinate` schema, with the grants.)
