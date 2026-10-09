# Conventions by area

Read the section for the area you are changing before you change it. The rules every change needs are in `CLAUDE.md`; these add what a single area needs. When you add a convention, put it here under its area, not in `CLAUDE.md`.

## Jobs (ADR 0015, 0029, 0033)

- A `unique_key` holds while a job with that key waits or runs: `enqueue` returns None meanwhile. A job that also runs on a schedule passes `schedule="<cron>"` to `@job`. A job whose worker died is settled by `platform.recover_stalled_jobs` (back to the queue, or `on_give_up` after its last attempt), so a handler must be safe to run again after doing part of its work.

## Email (ADR 0017)

- Email goes only through `modules/notifications/service.py` and is sent from background jobs. Never put a secret token in job arguments, because the queue keeps them (ADR 0017). Settings are `LISTENUP_SMTP_*`; tests swap the transport with `notifications.service.use_transport`.

## Uploads, media and the library (ADR 0020, 0022, 0027)

- Uploads go straight from the browser to storage (ADR 0020): `POST /uploads` records a row in `content.uploads` and returns a PUT URL signed for the exact type and size; `POST /contents` confirms it. Limits are `LISTENUP_UPLOAD_*` settings. `Storage` has `head` and `delete`; tests swap `app.state.uploads.storage` for the fake in `tests/integration/intake_helpers.py`.
- Media files of an upload live under `users/<user id>/media/<media id>/` (`playback.mp4`, `peaks.json`); the conversion job `content.convert_upload` (ADR 0022) runs ffprobe and ffmpeg as async subprocesses in `LISTENUP_MEDIA_SCRATCH_DIR`. The browser plays media through `GET /api/v1/media/{media_object_id}` (and `/peaks`), which checks for the caller's content item and redirects (307) to a signed storage URL; never put storage URLs in cached API bodies.
- Intake admission (ADR 0027): new audio counts per UTC day in `ops.rate_counters` (`intake:user:<id>`), at most 15 minutes a clip, added when the conversion job makes the clip playable; clips still being prepared reserve 15 minutes each. `POST /uploads` and `POST /contents` refuse with 429 `daily_audio_limit`. At most `LISTENUP_INTAKE_RUNNING_LIMIT` of a learner's conversions are on the intake lane; the rest wait with `content.uploads.queued_at` NULL until one ends. The conversion job records `media_objects.stage` and publishes `job.progress`; a removed duplicate answers 410 `duplicate_upload`. The storage cap counts `playback_bytes` once a clip is playable.
- List endpoints page by keyset: an opaque `cursor` (`content/domain/cursor.py`) and `next_cursor` in the response, never OFFSET.

## Plans and modes (ADR 0021, 0023 to 0025)

- Session writes carry the version the client last saw: `PATCH /sessions/{id}/entry` and `POST /sessions/{id}/steps/{step}/skip` take `version` in the body (409 `session_changed`). Plans start only on playable clips through `practice.service.start_plan` (409 `content_not_ready`, ADR 0023).
- Blind (ADR 0024): the heartbeat rules are the pure `judge` in `modules/blind/domain/listen.py`, and the gist sentence rule is `domain/gist.py` (mirrored in `apps/web/src/features/blind/gist.ts`). Routes take the time from the `server_now` dependency, which tests override. Blind media goes only through `GET /blind/attempts/{id}/media/{token}`, a redirect signed with `signed_download(..., ttl_seconds=...)` for the attempt's window.
- Dictation drafts save with `PUT /dictation/attempts/{id}/draft` and the `draft_version` the client last saw (409 `draft_conflict` with the current draft); `POST /sessions/{id}/dictation/attempts` resumes the live attempt instead of voiding it (ADR 0025).

## AI layer (ADR 0028)

- AI (ADR 0028): callers use `get_gateway()` from `listenup.ai.gateway` and the types in `listenup/ai/ports.py`. Only `grading` and `transcript` may import `listenup.ai`, and vendor libraries only `ai/providers/` (import-linter and `tests/architecture/test_ai_boundaries.py`). Providers per role are listed in `listenup/ai/ai.yaml` (`LISTENUP_AI_CONFIG` overrides it; `ai.fake.yaml` selects the fakes, which production refuses). A new provider is one adapter in `ai/providers/` plus one line in `ai/registry.py`; contract tests replay `tests/contract/recordings/*.json`, recorded with `scripts/record_ai_contract.py`.

## Data export (ADR 0030)

- Data export (ADR 0030): a module that owns learner data offers `export_data(session, learner) -> ExportPart` (from `listenup.platform.export`) in its `service.py`, using `learner_rows(..., omit=(secret columns,))`, and is listed in `modules/export/collect.py`; `test_export.py` fails while a table with `user_id` is missing from the export. YouTube media files are never exported. `POST /me/exports` queues `export.build_archive`; the archive is reached only through `GET /me/exports/{id}/download` (a 307 to a short-lived signed link) and is deleted after `LISTENUP_EXPORT_KEEP_DAYS`.

## Accounts and deletion (ADR 0017, 0029)

- Every way of signing in ends in `Accounts.complete_sign_in` (`modules/identity/service.py`), which owns the restore step of an account waiting for deletion (409 `account_pending_deletion` until the learner sends `restore: true`). Google sign-in (#32) must call it too.
- A disabled account reaches nothing: `identity.resolve_auth_session` returns a learner only while `users.status = 'active'`. Background work that must not run for a deleted account checks `identity.service.account_is_active` (the export build does).
- The purge (`identity.purge_account`) deletes storage under `users/<id>/` first, then the `identity.users` row, then performs a final prefix sweep before it marks the request completed. A failed final sweep leaves the request at `storage_deleted`; retries preserve its earlier row-count report. Every learner table must be deleted with the user (a foreign key to `identity.users`, or to a parent that has one, with `ON DELETE CASCADE`), so a new table needs no purge code; `test_account_deletion.py` fails while any row with the learner's `user_id` survives. A module that keeps a learner's files outside `users/<id>/` needs its own step in the purge. Rate counters about a learner use keys ending in `:user:<id>` (`user_key` in `platform/rate_limit.py`), which the purge removes.
- Password reset and account deletion both lock live reset-token rows before the learner's `identity.users` row. Keep that order when either flow changes; the concurrency regression in `test_account_deletion.py` proves they cannot deadlock.

## Operations: telemetry and backups (ADR 0031, 0032)

- Spans and instruments live only in `listenup.platform.telemetry`, written by hand on an attribute allowlist (no contrib auto-instrumentation: our paths carry signed media tokens). Off unless `LISTENUP_OTEL_ENABLED`; tests use `tests/telemetry_helpers.capture()`. Never put an email, free text, a URL with a token or an exception message on a span, a metric label or a log line; the log formatters replace email-shaped text with `[email]`.
- `enqueue` stores the request id and the W3C trace context in the job's arguments (`_request_id`, `_trace`); the `@job` wrapper pops both before the handler runs, so handlers never see them. A new job needs nothing for tracing or job metrics.
- The AI gateway (#64) calls `record_ai_call` and `record_ai_quota`, and grading jobs call `record_grading`; the alert rules already read those metrics. A new alert goes in `infra/observability/alerts.yml` with a case in `alerts.test.yml` (it fires, and stays quiet just below the threshold), a `runbook` entry in `docs/runbooks/alerts.md`, and a row in ADR 0031.
- Backups are `python -m listenup.ops.backup` (the `backup` image target). A backup is complete only with its `manifest.json`; the restore test is a monthly run recorded in the log at the end of `docs/runbooks/backups.md`. A migration that adds a schema or role must keep a restore into a database with the roles in place working (`tests/integration/test_backup.py`).

## Web client (ADR 0018, 0025, 0026)

- Confirmations use `ConfirmDialog` (`src/components/ConfirmDialog.tsx`): focus starts on the safe action, stays inside, and Escape cancels. Session data lives under the `['sessions']` query key (`src/features/session/api.ts`).
- Routes live in `src/App.tsx` (lazy pages; guards `RequireAuth` and `RedirectIfSignedIn` in `src/app/guards.tsx`). Design tokens are Tailwind theme variables in `src/index.css` (`bg-surface-raised`, `text-ink-muted`, `text-title`). Show API errors with `ErrorPanel` (ADR 0018). Live events map to query keys in `queryKeysForEvent` in `src/app/guards.tsx`. A live event that ends the stream (`account.disabled`) is listed in `STREAM_ENDING_EVENTS` on the server, so a replay ends it too.
- The passage picker (#42, ADR 0026) draws the server's peaks without wavesurfer.js: the rules are pure functions in `src/features/session/passage.ts`, the state is the reducer in `passageState.ts`, and the handles are `role="slider"` elements in `Waveform.tsx`. Playwright does not follow redirects for routed requests, so e2e fakes answer `/api/v1/media/{id}` and `/peaks` directly.
- Drafts and marks save through `src/lib/autosave` (`useAutosave`, `SaveStatus`): a local copy at once, a server save 2 s after the last edit on the server's version, `SaveConflict` on a stale version (ADR 0025). The Dictation player's control policy is `src/features/dictation/policy.ts`; Blind's playback policy and heartbeat protocol are in `src/features/blind/listen.ts`, and it reports a leave with `api(..., {keepalive: true})` because sendBeacon cannot send the CSRF header.
- Clip notices (`src/features/content/ClipNotices.tsx`) turn `content.ready` into a polite live-region notice that never takes focus and waits while a `/sessions/` page is open. Upload refusals map to messages in `src/features/library/refusals.ts`.
- Account settings live at `/settings` (`src/features/account/SettingsPage.tsx`); each section is its own component (`DataExportSection.tsx`, `DeleteAccountSection.tsx`).
