# ADR 0027: Intake admission per learner, progress stages and clear refusals

- Status: Accepted
- Date: 2026-10-03
- Source: issues #39, #40 and #41; [SRS FR-CI-3, FR-CI-5, NFR-USE-3, C2](https://claude.ai/code/artifact/fd47a9cb-6515-4fde-a232-3ab8cc14f0dd); [System Design 3.1, 4.1, 4.2, 9.1, 11.1](https://claude.ai/code/artifact/98274889-96ba-4424-afad-c2cd056206e2); [Database Design 7 (`ops.rate_counters`, key `intake:user:<id>`) and 12.3 (server and sessions in UTC)](https://claude.ai/code/artifact/ba05f7b3-f881-41e5-86d6-dcb94a509644); [Software Architecture 9.1 (rate limits per user and per IP on intake)](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13); D5, D16; ADRs 0016, 0020 and 0022

## Context

ADR 0022 left the daily limit of new audio (D16: 120 minutes per learner per day, configurable) open, because the sources seemed to disagree: SRS FR-CI-3 says intake beyond it is rejected with a clear message, while System Design 4.2 says "excess intakes wait in the learner's own queue rather than the shared one". The length of a clip is only known after ffprobe runs in the conversion job, a clip may be hours long although a passage is at most 15 minutes (C2), and the ux-lead assumed the limit resets at the learner's local midnight while the server stores no time zone. The other open points: what "at most 2 intakes running" means when the media pool runs one intake at a time anyway (System Design 4.1), how the learner sees progress (#40), and the duplicate-upload message ADR 0022 left out.

## Decision

### Two limits, two behaviours

Read together, the sources describe two different limits. Issue #41's acceptance criteria settle which behaviour belongs to which: "a third waits and shows queued" for running intakes, and "further new audio is refused with a message saying when the cap resets" for the daily cap. So the daily cap refuses (FR-CI-3) and the running limit queues (System Design 4.2).

### The daily cap is checked before upload and on confirmation; the job only counts

- **What counts.** A clip made playable counts its length to the nearest second, but at most 15 minutes, the longest passage (C2). What costs shared compute is transcription and profiling of the chosen passage, never more than 15 minutes per plan, while conversion of a long file is cheap next to it. Counting the whole clip would make any clip over 120 minutes impossible to add, against C2 and D2. Duplicates (merged before conversion), failed files and anything never converted count nothing. Shared YouTube media already in the system will count nothing when YouTube intake arrives (#41: "reused shared media does not count").
- **Where it is counted.** The conversion job adds the seconds to `ops.rate_counters` under `intake:user:<id>` with a one-day window, in the transaction that makes the clip playable, so a retried job never counts twice. The counter helpers (`add_to_window`, `window_count` in `platform/rate_limit.py`) run in the caller's transaction, unlike `RateLimiter.hit`.
- **Clips still being prepared reserve 15 minutes each,** the most a clip can count, since their length is unknown. A learner can therefore never have more than a day's allowance in flight.
- **The rule** (`content/domain/admission.py`): a new clip is allowed while the day's count plus the reservations is under the limit. The clip that crosses the limit is let in whole, so a day ends at most 15 minutes over it; refusing a clip for its last few minutes would make learners trim files to fit a number they cannot see in advance.
- **Where it is enforced.** `POST /uploads` refuses before any byte is sent, so a learner at the limit never uploads 500 MB for nothing, and `POST /contents` checks again under the learner's upload lock, because other clips may have been confirmed meanwhile. Both answer 429 `daily_audio_limit` with `Retry-After`, `used_seconds`, `limit_seconds`, `clips_in_progress` and `resets_at`. The conversion job never refuses on the cap: by then the file is uploaded and the clip was admitted.
- **Rejected alternatives.** Refusing in the conversion job after ffprobe wastes the upload and fails an item the learner already saw added. Deferring the conversion to the next day (System Design's "wait") would keep the original in storage, counting against the 2 GB cap, with no way for the learner to choose. Trusting a duration sent by the browser would let any client skip the cap.

### The day is the UTC day

The server and database run in UTC (Database Design 12.3), the counter window is anchored at midnight UTC by `date_bin`, and no learner time zone is stored. A time zone sent by the browser could be changed at will to start a new day, and two devices of one learner could disagree. The message from the API says "after midnight UTC, in 5 hours 30 minutes"; the web app formats `resets_at` in the learner's own time ("at 06:00 tomorrow" in Dhaka). Storing a profile time zone, if the product wants local-midnight resets, is a later change to the window anchor only.

### At most two intakes per learner on the shared lane; the rest wait in their own queue

The stage 0 media pool runs one intake job at a time, so "running" means on the shared intake lane, waiting or running. When an upload is confirmed it stays in the learner's own queue (`content.uploads.queued_at` is NULL, migration 0011) while two of the learner's conversions are on the lane (`LISTENUP_INTAKE_RUNNING_LIMIT`). Every end of a conversion (playable, failed, duplicate, item gone, last attempt failed) moves the learner's oldest waiting upload onto the lane in the same transaction (`jobs.start_waiting_uploads`, under the per-learner advisory lock that confirmation also takes). One learner adding twenty clips therefore never sits ahead of another learner's single clip. Every confirmation also fills free places, so a missed release heals on the learner's next upload. Jobs now carry `user_id`; jobs queued before this change end without starting the next one.

### Progress stages

The conversion job records `content.media_objects.stage` ('checking', 'converting', 'saving') and publishes `job.progress` for each learner with an item on the media object, in the transaction that stores it; reaching playable or failed clears it. Items in the API (`GET /contents`, `GET /contents/{id}`, `GET /library/contents`) return a derived `stage`: `queued` with `queue_position` in the learner's own queue, `waiting` on the lane, or the job's stage. Events still carry ids only (ADR 0016). In the web app `job.progress` refreshes the library and the clip, and `content.ready` for a clip whose page is not open shows a notice in a polite live region (ready, could not be prepared, or already in the library). Notices never take focus, stay until dismissed or followed, and wait while a practice session is open so nothing is announced over Blind or Shadow audio. The library badge is not a live region, because several clips in progress would announce every stage; the notice announces each clip once.

### Clear refusals

- **Duplicates.** The job remembers a removed duplicate in `content.duplicate_uploads` (the removed item's id, the learner, and the item kept), and `GET /contents/{id}` for the removed id answers 410 `duplicate_upload` with `existing_content_id` and `existing_title`. Another learner still gets 404 `content_not_found` (row-level security). The row goes with the kept item and the account.
- **The storage cap counts what is stored**, as #39's technical note asks: the playback file of a playable clip (`playback_bytes`), the original while a clip is being prepared or an upload may still be confirmed, and nothing for a failed clip, whose original is deleted. This replaces the count of declared sizes from ADR 0020.
- **Messages.** Every API refusal says what happened and what to do next; the web app gives each refusal code its own title and checks type, size, storage and the daily allowance before upload. The failure message for `processing_failed` no longer tells the learner to delete the clip, since deleting (FR-CI-7) is not built yet.
- **Per-IP limit.** `POST /uploads` is also limited per IP (`LISTENUP_UPLOAD_IP_LIMIT`, 120 an hour), besides the per-learner limit (Architecture 9.1).

## Consequences

- `ops.rate_counters` is UNLOGGED: a database crash forgets the day's counts, which only loosens the cap for one day.
- A clip reserved on one day and converted after midnight counts on the new day.
- A conversion job lost without ending (for example deleted from the queue by hand) keeps its place on the lane until the item is deleted; the admin view of failed jobs (System Design 11.1) is where that shows.
- `transcribed` and `profiled` readiness stages (System Design 3.1) and the retry action for failed downloads come with transcription and YouTube intake; YouTube items will reuse `stage` with `downloading`.
- `content.duplicate_uploads` rows are tiny and kept until the kept item or the account goes; a sweep can drop old ones if they ever matter.
