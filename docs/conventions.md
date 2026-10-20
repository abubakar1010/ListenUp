# Conventions by area

Read the section for the area you are changing before you change it. The rules every change needs are in `CLAUDE.md`; these add what a single area needs. When you add a convention, put it here under its area, not in `CLAUDE.md`.

## Jobs (ADR 0015, 0029, 0036)

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
- Dictation submit (#54, ADR 0042): `POST /dictation/attempts/{id}/submit` stores the text as `waiting_transcript`, completes the step and queues `dictation.score_attempt`; the job is the only scorer (idempotent conditional update, then `dictation.scored`). Reference words come only from `transcript.service.reference_for_scoring` and reach a response only inside `result.items`. A mode that must wait for the passage words registers with `transcript.service.on_passage_ready` (and `on_passage_failed`) from its `jobs.py`; hooks run in their own learner-scoped transaction after `transcript.ready` is committed, so a failing hook retries the job and never takes the event with it; `transcript.jobs` imports no mode (`practice` would reach it, `lint-imports`). Learner corrections (#56) plug in at `dictation.service.reference_words`.

- Blind's first network recovery must arrive before five minutes after its last accepted heartbeat (ADR 0024). `Listen.abandonment_deadline()` is shared by heartbeat validation and worker expiry. Granting a resume queues the shorter expiry check; a completed listen is preserved. Dictation's analytics callback runs on media `playing`, not `play`.

## AI layer (ADRs 0028, 0037, 0041)

- B2 alignment benchmarks import the production pure text helper from `ai/providers/alignment_text.py`; never expand contractions or normalize accents differently in the harness. Boundary validation matches text before measuring timestamps, reports unmatched coverage, and cannot pass incomplete hand labels. Alignment provenance includes window size and quantization, since both can change output for the same model (ADR 0034, NFR-AI-5).

- AI (ADR 0028): callers use `get_gateway()` from `listenup.ai.gateway` and the types in `listenup/ai/ports.py`. Only `grading` and `transcript` may import `listenup.ai`, and vendor libraries only `ai/providers/` (import-linter and `tests/architecture/test_ai_boundaries.py`). Providers per role are listed in `listenup/ai/ai.yaml` (`LISTENUP_AI_CONFIG` overrides it; `ai.fake.yaml` selects the fakes, which production refuses). A new provider is one adapter in `ai/providers/` plus one line in `ai/registry.py`; contract tests replay `tests/contract/recordings/*.json`, recorded with `scripts/record_ai_contract.py`. Speech adapters decode audio with ffmpeg (`ai/providers/audio.py`) and hand samples to the library, never a file path to the library's own decoder (ADR 0034). Model sizes and settings are chosen by the spikes in `spikes/` and recorded in an ADR; a recording is made with the models and options in `ai.yaml`.

- Gateway safeguards (ADR 0041): every attempt reserves persistent quotas before inference and logs content-free provenance. Use `CallContext` for eligibility, audio budgets, round and queue delay, never learner identity; optional `Usage` counts cache/reasoning inside input/output totals. Keep adapter output caps consistent with `ProviderEntry`. Text task overrides reference role provider IDs. `AIUnavailable.reason == "template_feedback"` asks grading to use deterministic templates; other unavailable results retain data for retry. `ai.maintain` refreshes quota metrics and monthly partitions. Accounting failure never permits unmetered calls.

- Token quota caps are supported only for text AI. Speech-role configuration with a `tokens` cap fails before adapter creation, including zero caps and provider IDs shared with text AI. Add a bounded speech token reservation contract before enabling token-metered speech (ADR 0041).

- Register content-free deployment version resolvers in `Registry.versions`; never use an inference response as the source of a log version. Unregistered adapters log NULL versions, and registered versions must match result provenance. Normalize Whisper timestamp jitter only inside its adapter (at most 100 ms per timestamp); the gateway keeps strict containment checks. Assessment words must match reference indexes/text, and sounds must remain ordered inside their word (ADR 0041).

## Transcripts (ADR 0038)

- Queue passage transcription through `transcript.service.queue_passage` in the plan-start transaction. Jobs use intake, a per-session unique key and per-media lock; all AI calls remain inside `transcript` through the existing gateway.
- Cache spans and word timings are absolute, half-open milliseconds. Only ready spans cover audio; process missing windows, preserve committed gaps on retry, and retain each span's provenance. Never weaken the database exclusion constraint to resolve a race.
- Transcript reads go through `transcript.service.read_passage` with the learner's RLS session and an explicit worker-role database. Ownership and `require_reached(TRANSCRIPT)` precede privileged reads. No direct API-role grant on the cache.
- Learner correction overlays use `(user_id, passage_transcript_id, word_index)` in `content.transcript_corrections` (ADR 0044). Read them in the learner's RLS transaction with an explicit learner filter after the gate; never mutate the cache. Preserve original sentence boundaries, word indices and timings, including empty replacements. The API has SELECT only; the editor/dispute write boundary remains #56. Export corrections through `transcript.service.export_data`.
- `sentence_starts` follows sentence-ending punctuation across provider chunks; do not equate acoustic segments with sentences. Ready cache rows require provider/model/version provenance and valid confidence/sentence-index arrays.
- `transcript.ready` and `transcript.failed` carry session IDs only. They are invalidation signals and may repeat after retries. Do not expose text through progress events.

## Data export (ADR 0030)

- Expiry handlers raise `Reschedule(deadline)` when not due; the worker postpones the job without producer deduplication or failure-budget consumption. Exhausted export builds queue independent `export.cleanup_archive` work; exhausted cleanup cycles schedule another cycle an hour later, preserving cleanup after restoration or purge.

- Rejected export archives are removed by their deterministic storage key on every build retry, including after the request is marked `account_deleted` and the account is restored or purged. A failed storage deletion must not become an early-return success on the next attempt.

- Data export (ADR 0030): a module that owns learner data offers `export_data(session, learner) -> ExportPart` (from `listenup.platform.export`) in its `service.py`, using `learner_rows(..., omit=(secret columns,))`, and is listed in `modules/export/collect.py`; `test_export.py` fails while a table with `user_id` is missing from the export. YouTube media files are never exported. `POST /me/exports` queues `export.build_archive`; the archive is reached only through `GET /me/exports/{id}/download` (a 307 to a short-lived signed link) and is deleted after `LISTENUP_EXPORT_KEEP_DAYS`.

## Accounts and deletion (ADR 0017, 0029)

- Every way of signing in ends in `Accounts.complete_sign_in` (`modules/identity/service.py`), which owns the restore step of an account waiting for deletion (409 `account_pending_deletion` until the learner sends `restore: true`). Google sign-in (#32) must call it too.
- A disabled account reaches nothing: `identity.resolve_auth_session` returns a learner only while `users.status = 'active'`. Background work that must not run for a deleted account checks `identity.service.account_is_active` (the export build does).
- The purge (`identity.purge_account`) deletes storage under `users/<id>/` first, then the `identity.users` row, then performs a final prefix sweep before it marks the request completed. A failed final sweep leaves the request at `storage_deleted`; retries preserve its earlier row-count report. Every learner table must be deleted with the user (a foreign key to `identity.users`, or to a parent that has one, with `ON DELETE CASCADE`), so a new table needs no purge code; `test_account_deletion.py` fails while any row with the learner's `user_id` survives. A module that keeps a learner's files outside `users/<id>/` needs its own step in the purge. Rate counters about a learner use keys ending in `:user:<id>` (`user_key` in `platform/rate_limit.py`), which the purge removes.
- Consents (#104, ADR 0048): every account is created with terms and privacy rows for the current `LISTENUP_TERMS_VERSION` and `LISTENUP_PRIVACY_VERSION`; a new sign-up path calls `Accounts.check_sign_up_consent` before creating the account and `record_sign_up_consent` after. A newer label reaches the learner as `Me.consents_required` and is accepted with `POST /me/consents`; until then `CurrentLearner` refuses with 403 `consent_required`. Only routes a learner who declines still needs (profile, consents, export, deletion, events) take `SignedInLearner`; every other route uses `CurrentLearner`. A module that records voice checks `identity.service.require_voice_consent(session, learner, settings)` with the app's settings (403 `voice_consent_required`) before each new round; only `voice_recording` can be withdrawn. Never write `identity.consents` from another module.
- Password reset and account deletion both lock live reset-token rows before the learner's `identity.users` row. Keep that order when either flow changes; the concurrency regression in `test_account_deletion.py` proves they cannot deadlock.

## Analytics (ADR 0035)

- Product events (PRD 8.2) are recorded on the server through `modules/analytics/service.py`, one call per place where the event happens, inside the request transaction that makes the change. Never insert into `ops.analytics_events` directly, and never put personal data or learner text in an event (a mark keeps only a learner-scoped HMAC of its normalised phrase). A repeat of the same (event, subject, step) is ignored, so callers need no checks of their own. Dictation records `listen_started` through its authenticated endpoint on the first successful media play; opening the screen is not a listen. Marks, cards, Shadow rounds and Dictation submission call `record_mark_created`, `record_card_created`, `record_shadow_round_completed` and `record_dictation_replays` when they are built. Blind queues a delayed expiry check so a vanished browser is still voided and recorded. The analytics module imports no other module. The success-metrics report is `scripts/analytics_report.py`, run as `listenup_readonly`, and refuses ranges that extend beyond `--as-of`.

## Operations: telemetry and backups (ADR 0031, 0032)

- Spans and instruments live only in `listenup.platform.telemetry`, written by hand on an attribute allowlist (no contrib auto-instrumentation: our paths carry signed media tokens). Off unless `LISTENUP_OTEL_ENABLED`; tests use `tests/telemetry_helpers.capture()`. Never put an email, free text, a URL with a token or an exception message on a span, a metric label or a log line; the log formatters replace email-shaped text with `[email]`.
- `enqueue` stores the request id and the W3C trace context in the job's arguments (`_request_id`, `_trace`); the `@job` wrapper pops both before the handler runs, so handlers never see them. A new job needs nothing for tracing or job metrics.
- The AI gateway (#64) calls `record_ai_call` and `record_ai_quota`, and grading jobs call `record_grading`; the alert rules already read those metrics. A new alert goes in `infra/observability/alerts.yml` with a case in `alerts.test.yml` (it fires, and stays quiet just below the threshold), a `runbook` entry in `docs/runbooks/alerts.md`, and a row in ADR 0031.
- Backups are `python -m listenup.ops.backup` (the `backup` image target). A backup is complete only with its `manifest.json`; the restore test is a monthly run recorded in the log at the end of `docs/runbooks/backups.md`. A migration that adds a schema or role must keep a restore into a database with the roles in place working (`tests/integration/test_backup.py`).

## Admin (ADR 0045)

- Admin routes live in `modules/admin/api.py` under `/admin` and take `CurrentAdmin` from `modules/admin/service.py`: a learner who is not an admin gets 404 `not_found`, the answer of a path that does not exist. Admins are the verified accounts whose email is in `LISTENUP_ADMIN_EMAILS`. Register admin routes as `Admin(...)` in `tests/integration/access_registry.py`.
- Admin answers carry counts, ids, names and times only: never job arguments, learner media or text (SRS 2.2). Failed jobs are retried as new jobs with `platform.jobs.retry_failed_job`. The web page is `/admin/jobs` (`src/features/admin/JobsPage.tsx`); on 404 it shows the ordinary "Page not found".

## Web client (ADR 0018, 0025, 0026)

- Account transitions use `auth/session.changeSession`: cancel outstanding reads before publishing sign-in, sign-out or a completed password reset. The query client clears private queries and mutation results whenever `/me` identifies a different learner or signs out (NFR-SEC-2). The protected subtree is keyed by learner id so account replacement also drops private notices and closes the previous live-events connection. Do not replace `me` directly from an authentication mutation; an older `/me` response could otherwise undo the transition.
- Only authentication mutations that synchronously publish their own session use `meta: { changesSession: true }`. Other mutations keep their originating account generation through completion; stale success, error and settlement callbacks are suppressed. Keep cache writes in the synchronous part of callbacks; a callback that awaits additional work must independently check its account scope before later writes. Regression tests cover response ordering, callback settlement and reuse of mutation options.
- Confirmations use `ConfirmDialog` (`src/components/ConfirmDialog.tsx`): focus starts on the safe action, stays inside, and Escape cancels. Session data lives under the `['sessions']` query key (`src/features/session/api.ts`).
- Routes live in `src/App.tsx` (lazy pages; guards `RequireAuth` and `RedirectIfSignedIn` in `src/app/guards.tsx`). Design tokens are Tailwind theme variables in `src/index.css` (`bg-surface-raised`, `text-ink-muted`, `text-title`). Show API errors with `ErrorPanel` (ADR 0018). Live events map to query keys in `queryKeysForEvent` in `src/app/eventKeys.ts`. A live event that ends the stream (`account.disabled`) is listed in `STREAM_ENDING_EVENTS` on the server, so a replay ends it too.
- The passage picker (#42, ADR 0026) draws the server's peaks without wavesurfer.js: the rules are pure functions in `src/features/session/passage.ts`, the state is the reducer in `passageState.ts`, and the handles are `role="slider"` elements in `Waveform.tsx`. Playwright does not follow redirects for routed requests, so e2e fakes answer `/api/v1/media/{id}` and `/peaks` directly.
- Drafts and marks save through `src/lib/autosave` (`useAutosave`, `SaveStatus`): a local copy at once, a server save 2 s after the last edit on the server's version, `SaveConflict` on a stale version (ADR 0025). The Dictation player's control policy is `src/features/dictation/policy.ts`; Blind's playback policy and heartbeat protocol are in `src/features/blind/listen.ts`, and it reports a leave with `api(..., {keepalive: true})` because sendBeacon cannot send the CSRF header.
- Clip notices (`src/features/content/ClipNotices.tsx`) turn `content.ready` into a polite live-region notice that never takes focus and waits while a `/sessions/` page is open. Upload refusals map to messages in `src/features/library/refusals.ts`.
- Account settings live at `/settings` (`src/features/account/SettingsPage.tsx`); each section is its own component (`DataExportSection.tsx`, `ConsentsSection.tsx`, `DeleteAccountSection.tsx`). `RequireAuth` shows `auth/ConsentPrompt.tsx` instead of a signed-in page while `me.consents_required` is not empty, except `/settings` and `/settings/delete-account`, and on a `/sessions/` page only after a request was refused with `consent_required` (ADR 0048); consent hooks live in `src/auth/consentApi.ts`.

## Google authentication (ADRs 0039, 0040)

- Google callbacks use Authlib and finish through `Accounts.complete_sign_in`.
  Resolve `(provider, subject)` before a verified-email link; a known subject must
  never move between users because its email changed. Google-verified email may
  link a locally unverified password account (owner-approved policy).
- OIDC callbacks, restoration continuations and deletion proofs use expiring,
  browser-bound database flows. Consume before external calls/account changes;
  never put provider tokens, restore proofs or deletion proofs in URLs, logs,
  exports or browser storage. Reauthentication must match the current linked
  subject and session, and deletion still needs the final explicit confirmation.
- Supply `LISTENUP_GOOGLE_CLIENT_ID`, `LISTENUP_GOOGLE_CLIENT_SECRET` and the exact
  registered `LISTENUP_GOOGLE_REDIRECT_URI` through the API environment. Google
  sign-in bypasses password lockout, retains IP limits and never silently restores.

- Google cannot be instructed to reauthenticate. Deletion confirmation requests
  the essential signed `auth_time` claim and requires the existing fresh-time
  boundary; `select_account`, consent and token issue time are never evidence of
  freshness. Operators must enable Google's Session age claims for a published,
  verified app. Stale sessions require separate Google sign-out followed by a new
  flow and Google sign-in; never weaken the check to make an old session pass.
- Expected full-page callback refusals redirect to `/auth/google-error` using only
  fixed reason/intent codes. Keep consumption single-use, roll back business
  writes on refusal, and expose an accessible control that starts a new flow.

## Transcript review (ADR 0044)

- Review composes `transcript.service.read_passage`; its worker-role database comes
  from `LISTENUP_TRANSCRIPT_READ_DATABASE_URL`. Keep the request connection on the
  API role and never grant it cache access. See ADR 0044 for the local/Compose setup.
- Transcript lines are sentences with absolute word timings and passage-global
  indices. Correction overlays belong inside the authorized transcript service (#56),
  before review groups words; review does not own correction persistence or autosave.
- Passage transport, controls and policy live in `features/media`; Dictation keeps
  compatibility exports. Transcript supplies sentence replay and keyboard handling.
  Readiness/failure events invalidate the named review query; pending reads also poll.
