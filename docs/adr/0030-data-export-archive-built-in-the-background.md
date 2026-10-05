# ADR 0030: Data export as a ZIP built in the background, reached through a redirect

- Status: Accepted
- Date: 2026-10-04
- Source: issue #92; [SRS NFR-SEC-5](https://claude.ai/code/artifact/fd47a9cb-6515-4fde-a232-3ab8cc14f0dd); [Software Architecture 8 (storage under `users/<id>/`, signed URLs), 9.2 (Account: `GET /me/export`) and 12.2 (Export: JSON plus media files, YouTube media excluded)](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13); D5, D10; ADRs 0005, 0013, 0015, 0016 and 0022

## Context

A learner can take a copy of their data on request (NFR-SEC-5). Issue #92 asks for a JSON file of every learner-owned table plus their uploads, packaged in storage and handed out through a short-lived signed link; YouTube media files are excluded by D10, while the learner's YouTube items are still exported as data. The design names the route `GET /me/export` but says nothing about the archive format, how long it is kept, how often a learner may ask, or how modules that do not exist yet (marks, cards, recordings, grades, consents) join the export.

## Decision

### Routes

- `POST /me/exports` starts an export and answers 202 with its status. The design's `GET /me/export` would start work on a GET, which browsers prefetch and which the CSRF middleware does not guard; every other write in the API is a POST with the `X-CSRF-Token` header. It accepts an `Idempotency-Key` like other submissions.
- `GET /me/exports/latest` returns the learner's most recent export (`{"export": null}` when there is none), with `download_url` set only while it is ready.
- `GET /me/exports/{id}/download` needs the owner's session (404 `export_not_found` for anyone else), and redirects (307, `Cache-Control: private, no-store`) to a storage URL signed for `LISTENUP_EXPORT_LINK_SECONDS` (120 s). No storage URL is ever put in a JSON body. 409 `export_not_ready` while it is built or after it failed; 410 `export_expired` after the keep period.

### Limits

- One export per learner is pending or building at a time (`data_exports_one_live`, a partial unique index); another request answers 409 `export_in_progress` with its `export_id`.
- At most `LISTENUP_EXPORT_DAILY_LIMIT` (3) requests per learner per UTC day, counted with `RateLimiter.enforce` under `export:user:<id>` (429 `rate_limited` with `Retry-After`). An export reads every table and copies up to the 2 GB upload cap (D5) through the worker, so a conservative limit protects the background lane; three a day still allows a retry after a failure.
- A finished archive is kept for `LISTENUP_EXPORT_KEEP_DAYS` (7) days. The build job queues `export.expire_archive` for that moment in the transaction that marks the export ready; it deletes the object and marks the row `expired`. The row stays as the record of the request. An account deletion removes the archive with everything else under `users/<id>/`.

### The build job

`export.build_archive` runs on the background lane (45-minute timeout, 3 attempts), one at a time per learner (`lock export:<id>`):

1. It marks the row `building`. A repeated run after a crash builds again; a run on a ready, failed or expired export does nothing.
2. It reads every module's part in one `REPEATABLE READ, READ ONLY` transaction, so sessions, steps and attempts agree with each other.
3. It writes a ZIP in scratch space: each file stored as it is (media is compressed already), then `data.json`. It uploads the ZIP to `users/<id>/exports/<export id>.zip`.
4. It marks the row `ready` with size, file count and expiry, publishes `export.ready` and queues the expiry, in one transaction. On the last failed attempt it marks the row `failed` (`export_failed`) and publishes `export.ready` too, so the page stops waiting and the learner can ask again.

The archive is a ZIP rather than a JSON file with links, so it can be kept offline as one file. Its layout:

```
data.json                      format, version, ids, time, tables, omitted_columns, files, missing_files
media/<media id>/playback.mp4  the playback file of every clip the learner uploaded
uploads/<upload id>.<ext>      originals of uploads not converted yet (when still in storage)
```

`data.json` maps each schema-qualified table name to its rows, with every column except the ones listed under `omitted_columns`. Values become JSON in `export/domain/archive.py`: ids and times as text, ranges as `{lower, upper, bounds}`. Each file is listed with its size and SHA-256.

### What is left out

- **YouTube media files**, always (D10, CLAUDE.md). Only `source = 'upload'` media uploaded by the learner contributes files; the YouTube item, its media row (video id, title, duration) and its practice are exported as data.
- **Secrets of the service**: `identity.users.password_hash`, `auth_sessions.token_hash`, `one_time_tokens.token_hash`, `blind_attempts.media_token_hash`, `idempotency_keys.request_hash`.
- **Internal or shared details**: media storage keys (`playback_key`, `video_key`, `peaks_key`), the archive key of earlier exports, and a media object's `ref_count` and `last_used_at`, which count other learners' use of shared YouTube media.
- **Not exported because it is not the learner's data**: `ops.rate_counters` (counters keyed by text, also by IP) and the job queue.
- The original of a converted upload is deleted by the conversion job (ADR 0022); the playback file is the stored copy of the learner's upload. Waveform peaks are derived from it and are not copied.

### How modules contribute

The export module never reads another module's tables. Each module that owns learner data offers `export_data(session, learner) -> ExportPart` in its `service.py`; `ExportPart`, `ExportTable`, `ExportFile` and the helper `learner_rows` live in `listenup/platform/export.py`, so modules return them without importing the export module (which imports them all, in `export/collect.py`). `learner_rows` selects every column with an explicit `user_id` filter, because the job runs as the workers' role, which bypasses row-level security; table and column names must be plain identifiers from code. `SELECT *` means a new column is exported without a code change, so a new secret column must be added to `omit`.

The job also refuses any file whose key is outside `users/<learner>/` or whose archive path is not a plain relative path, so a mistake in one module can never copy another learner's file.

`tests/integration/test_export.py` lists every application table with a `user_id` column from `information_schema` and fails while any of them is missing from the export, and checks that no other learner's id appears in it. Marks, cards, grades, consents and Shadow recordings do not exist yet: when their stories add the tables, the owning module adds them to its `export_data` (recordings and card snippets as `ExportFile`s under the learner's prefix), and a module with its first learner table adds its function to `CONTRIBUTORS`.

### Live update

`export.ready` is a new event type (ADR 0016); it carries the export id and is published for both ready and failed exports. The web app refetches the latest export on it, and polls every 5 s while an export is pending or building, in case the stream is down.

## Consequences

- The design's `GET /me/export` becomes `POST /me/exports` plus two GET routes; the Software Architecture's API table should be updated to match.
- A learner with a full 2 GB library makes a 2 GB archive, briefly doubling their storage for up to 7 days; archives are not counted against the upload cap.
- The background lane runs one job at a time (System Design 4.1), so a large export delays password-reset emails behind it by minutes. If that becomes a problem, exports can move to their own lane.
- A future change to the archive layout bumps `version` in `data.json`.
