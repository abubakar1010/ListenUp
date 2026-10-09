Source: https://claude.ai/code/artifact/98274889-96ba-4424-afad-c2cd056206e2 · Exported 2026-10-09

# ListenUp System Design

Oct 2, 2026 · @Md. Ebrahim Hossen

## 1. Summary

The system is designed so that **one free 4-core server can serve about 150 daily learners**, and every step beyond that is a planned move with a measurable trigger, not a redesign. It builds on the [ListenUp Software Architecture](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13) and refines it where efficiency requires (section 12).

All figures marked **(est.)** are planning estimates from typical model performance. They must be confirmed by the benchmarks in section 12 before launch.

### 1.1 Design targets

| Target | Value |
| --- | --- |
| API response time, reads | p95 under 200 ms |
| API response time, writes | p95 under 300 ms |
| Playback start after a step opens | Under 2 s |
| YouTube link to playable (10-minute clip) | p95 under 45 s |
| Passage transcript ready after playable | p95 under 2 min |
| Gist grade shown after submit | p95 under 10 s |
| Shadow round feedback after the round ends | p95 under 60 s |
| Three-round comparison after round 3 feedback | p95 under 30 s |
| Monthly availability (practice screens) | 99.5% |
| Cost at stage 0 | Zero |

### 1.2 The ideas that make it efficient

1. **Progressive readiness.** Blind needs only playable audio, not a transcript, so the learner starts practicing while transcription runs in the background.
2. **Do only the work the learner chose.** Transcribe and analyse the selected passage, not the whole clip.
3. **Compute once, reuse everywhere.** A shared YouTube video is downloaded, transcribed and profiled once, then reused by every learner who picks it (access stays private per learner).
4. **Reference profiles.** The original speaker's word timings, sounds and pitch for a passage are computed once; each Shadow round then analyses only the learner's audio.
5. **Deterministic first, AI last.** Scores come from code and speech models; the text AI only writes words, and gets a few hundred tokens of numbers rather than raw audio or long text.
6. **Priority queues with backpressure.** Work a learner is waiting for always runs before background work, and intake is rate-limited per learner to protect shared compute.
7. **Compact data.** Transcript words are stored as packed arrays, heartbeats update one row in place, and logs are partitioned and expired.

## 2. Capacity estimates

Speech processing on CPU is the bottleneck: an average session costs about **7 core-minutes**, which caps one free 4-core server at roughly **150 daily learners**; storage and AI quotas run out later than compute.

### 2.1 Assumptions (est.)

| Input | Value |
| --- | --- |
| Sessions per daily learner | 1 per day, about 30 minutes |
| Passage length | 3 minutes (the default) |
| Shadow rounds | 3 rounds of about 75 s |
| New passage vs reused | 50% new; the rest are library repeats or a YouTube video another learner already used |
| Busiest hour | 15% of the day's sessions |
| Target CPU use at peak | 70% |

### 2.2 Compute per session (est.)

| Work | Core-seconds per audio-second | Per session |
| --- | --- | --- |
| Download and audio conversion (10-minute clip) | n/a | about 15 core-s |
| Transcription of the passage (small English model, int8, silence skipped) | about 1.0 | about 180 core-s |
| Reference profile of the passage (alignment, sounds, pitch) | about 0.5 | about 90 core-s |
| Shadow round analysis, 3 rounds | about 1.2 | about 270 core-s |
| **Total, new passage** |  | **about 555 core-s (9 core-min)** |
| **Average with 50% reuse** |  | **about 420 core-s (7 core-min)** |

One 4-core server gives 240 core-minutes per hour, or 168 at 70% use. With 15% of the day in the busiest hour, that supports about 168 / 0.15 / 7 = **160 learners a day**. A round's 90 core-seconds on 2 threads finishes in about 45 s, inside the 60 s target when nothing is queued.

### 2.3 Per stage

|  | Stage 0 | Stage 1 | Stage 2 |
| --- | --- | --- | --- |
| Daily learners | up to 150 | up to 1,500 | up to 15,000 |
| Learners online at peak | about 11 | about 110 | about 1,100 |
| API requests per second at peak | about 15 | about 150 | about 1,500 |
| Speech compute per day | about 1,050 core-min | about 10,500 core-min | about 105,000 core-min |
| Compute needed | 1 free 4-core server | about 10 cores or 1 small GPU | a GPU pool that scales with queue depth |
| New media per month (audio only) | about 7 GB | about 70 GB | about 700 GB |
| Database growth per month | about 40 MB | about 400 MB | about 4 GB |
| AI text calls per day (standard / quota-saving mode) | about 825 / 375 | about 8,250 / 3,750 | about 82,500 / 37,500 |
| AI tokens per day | about 2 million | about 20 million | about 200 million |

**Per learner per month (est.):** 10 new clips at 64 kbit/s AAC (about 29 MB after deduplication), 60 Shadow recordings at 24 kbit/s Opus (about 14 MB), and about 0.25 MB of database rows. Video at 360p would add about 375 MB, which is why video is opt-in (section 6).

The API itself is never the constraint at these sizes: 15 requests per second is a few percent of one Python process.

## 3. Latency budgets and progressive readiness

A learner should never wait for work that the current step does not need, so content becomes usable in stages and each slow result is split into a fast part and a slower part.

### 3.1 Content readiness stages

| Stage | Reached when | Unlocks |
| --- | --- | --- |
| `playable` | Audio is in storage in the playback format | Blind, and Dictation typing |
| `transcribed` | The chosen passage has words with times | Dictation scoring, Transcript step, key-point extraction |
| `profiled` | The original's reference profile for the passage exists | Shadow |

Blind takes the length of the passage (3 minutes by default) plus the gist, so transcription and profiling normally finish before the learner needs them. If a learner submits Dictation before the transcript is ready, the text is saved and scored automatically when it arrives.

### 3.2 Budgets

| Path | Budget (p95) | Breakdown |
| --- | --- | --- |
| Playback start | under 2 s | signed URL 30 ms, first byte from storage under 300 ms, MP4 with the index at the front ("faststart") so playback begins on the first bytes |
| YouTube link to `playable` (10-minute clip) | under 45 s | metadata 3 s; audio download 5 to 20 s; **no re-encoding** when YouTube already offers AAC audio (copy the stream into MP4, about 1 s); otherwise encode, about 10 s |
| `playable` to `transcribed` (3-minute passage) | under 2 min | queue wait under 10 s, transcription about 45 to 60 s on 4 threads (est.) |
| Gist grade | under 10 s | queue wait under 1 s, AI call 3 to 6 s, validation and storage 50 ms, live event 100 ms |
| Shadow round: scores | under 50 s | upload of about 0.2 MB in 1 to 2 s (section 9), queue wait under 2 s, analysis about 45 s, scoring 1 s |
| Shadow round: written feedback | under 60 s | scores plus one AI call of 3 to 6 s |
| Mark saved | under 1 s, shown instantly | optimistic update in the browser, one INSERT on the server |

**Two-phase results.** Shadow scores and word labels are shown as soon as the speech analysis finishes; the AI-written feedback appears a few seconds later in the same panel. The learner sees useful output well before the slowest part completes.

## 4. Job system

All background work flows through four priority lanes in the PostgreSQL queue, served by two worker pools sized to their resource: CPU-bound speech work and network-bound AI calls. Lanes are Procrastinate queues, each with a priority (lane 1 highest); the queue's tables live in a procrastinate schema that migration 0003 creates from Procrastinate's own SQL, vendored at the installed version, and the database's search path includes procrastinate after public.

&#91;embedded content: job system · 4 priority lanes, 2 worker pools\]

### 4.1 Lanes

| Lane | Jobs | Pool | Concurrency | Timeout | Max attempts |
| --- | --- | --- | --- | --- | --- |
| 1 `speech-interactive` | Shadow round analysis, three-round comparison | media | both slots | 3 min | 3 |
| 2 `intake` | Metadata, download, conversion, passage transcription, reference profile, card snippets | media | 1 slot | 10 min | 5 |
| 3 `ai` | Key points, gist grade, round feedback, suggestions | default | 8 async | 60 s | 4 (with provider fallback inside each attempt) |
| 4 `background` | Email, deletion, retention sweeps, trends, scratch clean-up; data export build | default | 1 | 15 min; export build 45 min | 5; export build 3 ([ADR 0030](../adr/0030-data-export-archive-built-in-the-background.md)) |

The two pools are separate processes, so a burst of AI calls (waiting on the network) never takes CPU from speech analysis, and vice versa. Each pool runs two Procrastinate workers: the media pool one on lanes 1 and 2 and one on lane 1 only, so speech work can use both slots and intake at most one; the default pool one with 8 concurrent AI jobs and one for background jobs.

Data exports run on the background lane, one pending/building export per learner and three requests per UTC day. A finished ZIP is retained seven days and fetched through an owner-only redirect signed for 120 s. The build's 45-minute timeout and three attempts are job overrides; a large export can delay password-reset emails on this single-concurrency lane ([ADR 0030](../adr/0030-data-export-archive-built-in-the-background.md)).

### 4.2 Rules

- **Transactional enqueue.** Jobs are inserted in the same transaction as the data that triggers them, so a job never runs for a change that was rolled back.
- **Retries.** Exponential backoff with up to 20% jitter (about 10 s, 40 s, 160 s), until the lane's attempt limit, after which the job is failed and listed for operators. A PermanentError (for example a validation error) fails the job at once; every other error, including a timeout, retries. Job timeouts are separate from the learner-facing deadlines: the learner sees "Feedback unavailable" with a retry when no result is ready 30 s after a gist, 120 s after a Shadow round, or 90 s after round 3 for the three-round comparison.
- **Unique job keys** prevent duplicates (for example two clicks on "retry"), and **locks per resource** coalesce identical work, such as two learners opening the same shared passage.
- **Chaining.** Each job enqueues the next step on success (download, then convert, then transcribe, then profile), so progress survives restarts and each step retries on its own.
- **Admission control.** Two distinct limits ([ADR 0027](../adr/0027-intake-admission-progress-and-refusals.md)): the 120-minute daily cap refuses new uploads with 429 `daily_audio_limit` and a reset time; the two-intake limit queues excess clips in the learner's own queue. “Running” means waiting or executing on the shared intake lane. The daily window starts at midnight UTC; display its reset time in the learner's local time. A playable clip counts its duration rounded to seconds, capped at 15 minutes; clips still being prepared reserve 15 minutes each. Duplicates, failed clips and reused shared media count nothing. Admit a new clip while used seconds plus reservations are below the cap, including the clip that crosses it (at most 15 minutes over). Check before upload and again on confirmation; count once in the conversion transaction, never reject in the conversion job. `content.uploads.queued_at` is NULL while waiting locally; each conversion end releases the oldest waiting upload under the per-learner lock, and confirmation fills free places too.
- **Backpressure.** When a lane 1 job has waited more than 30 s, lane 2 pauses: intake jobs re-queue themselves 10 s later without using up an attempt. Intake resumes only when lane 1 has drained completely, so the pool does not flap; when the AI quota is low, lane 3 switches to quota-saving mode (section 7).

## 5. Speech compute efficiency

Speech work is the main cost, so the design avoids repeating it, keeps models loaded, and picks the smallest model that passes the golden set.

### 5.1 Do less work

- **Passage-only processing.** Transcribe and profile the chosen passage plus 5 s on each side (to avoid cutting words), never the whole clip. Results are cached by (media fingerprint, start, end); overlapping later requests reuse the cached words and process only the missing span.
- **Skip transcription when captions exist.** Creator captions need only forced alignment, about a fifth of the cost of transcription (est.).
- **Silence skipping.** A voice-activity detector removes silence before transcription and round analysis.
- **Reference profile once.** For each passage, the original speaker's word and sound timings, pitch contour, stress and speech rate are computed once at `transcribed` time and stored (about 50 KB). Each Shadow round analyses only the learner's 75 s and compares against the stored profile, which roughly halves the work per round.
- **One acoustic pass per round.** The phoneme model runs once per recording; its output feeds pronunciation, articulation and completeness. Pitch and intensity (Parselmouth) are cheap and run alongside.
- **Filler pass on the recording only.** The disfluency-keeping transcription pass runs on the 75 s recording, not on the passage.

### 5.2 Run it efficiently

- **Warm models.** Each media worker process loads its models once at start-up and keeps them in memory. A health check fails until loading finishes, so no job pays a cold-start cost.
- **Quantised, English-only models.** int8 weights and English-only model variants; the smallest size that meets the accuracy threshold on the golden set wins.
- **No thread oversubscription.** Each worker process gets a fixed thread count (for example 2 threads, 2 processes on a 4-core server), set through the inference library and `OMP_NUM_THREADS`, so jobs do not fight over cores.
- **Memory budget.** Speech models are loaded in the media worker only; the API and default worker stay small. The media image alone installs the optional `speech` extra and CPU-index torch/torchaudio; `base.en` and `MMS_FA` download about 1.3 GB on first start into `/models`, with configured preloading before readiness and fixed CPU threads. These provisional models await spike results ([ADR 0028](../adr/0028-ai-ports-gateway-and-self-hosted-speech-adapters.md)). The self-hosted LLM is optional on stage 0 because a CPU LLM competes with speech work for the same cores; it is enabled only when hosted AI quotas run out.
- **GPU switch point.** Move speech work to a GPU when peak CPU stays above 70% for a week or round feedback p95 exceeds 60 s. A modest GPU typically runs these models many times faster than CPU (est.), which is cheaper per round than adding CPU servers beyond stage 1.

## 6. Media and storage efficiency

Storage stays small by keeping one compact playback file per clip, sharing YouTube media between learners, deriving analysis audio on demand, and expiring what can be fetched again.

### 6.1 Formats

| File | Format | Size (est.) | Kept |
| --- | --- | --- | --- |
| Playback audio | AAC-LC, mono, 64 kbit/s, MP4 with faststart | about 0.5 MB per minute | Yes |
| Playback video (opt-in only) | H.264 360p plus the audio above | about 3.7 MB per minute | Yes, if chosen |
| Analysis audio | 16 kHz mono PCM | about 1.9 MB per minute | **No**: decoded into worker scratch space when needed, deleted after the job |
| Source download or upload | As received | varies | **No** for YouTube (deleted after conversion); uploads converted, then the original is deleted |
| Shadow recording | Opus 24 kbit/s (WebM) or AAC (Safari), as recorded | about 0.2 MB per round | 90 days, scores kept |
| Card snippet | AAC, 3 to 6 s | about 50 KB | Until the card is deleted, so cards survive media expiry |
| Waveform peaks | JSON, computed at intake | about 2 KB per minute | With the clip; the browser never decodes audio to draw it |

### 6.2 Shared YouTube media

A `media_objects` table holds one row per distinct source, keyed by a fingerprint (`youtube:<video id>`; uploads use a SHA-256 hash scoped to the uploading learner). Each learner's content item points to a media object. A second learner adding the same YouTube video gets it instantly, with its cached passage transcripts, reference profiles and key points.

- Uploads are **never shared across learners**, even when identical, so one learner's files cannot reveal anything to another.
- A media object is deleted when no content item references it (reference counting in the same transaction as the content deletion).
- Sharing also means each YouTube video is downloaded once, which reduces download traffic and the legal exposure discussed in OQ-6.

### 6.3 Retention

| Data | Rule |
| --- | --- |
| YouTube playback files | Deleted after 30 days without any session using them; metadata, transcripts and profiles are kept, and the file is re-downloaded on next use |
| Uploaded playback files | Kept until the learner deletes them; a per-account cap of 2 GB of stored uploads, and 500 MB per file |
| Shadow recordings | Deleted 90 days after recording; grades and word labels stay |
| Worker scratch files | Deleted at the end of every job, and a sweep removes anything older than 1 hour |

### 6.4 Delivery

Media is served straight from object storage with signed URLs and HTTP range requests, never through the API. Stage 0 needs no CDN for media when the storage provider charges nothing for downloads; from stage 2 a CDN with signed tokens sits in front of the bucket.

## 7. AI quota and cost efficiency

A session needs at most about 5 text-AI calls and 14,000 tokens, and a quota-saving mode cuts that by more than half, so free tiers last as long as possible and a paid switch stays cheap.

### 7.1 Calls per session

| Task | Calls | Input sent | Tokens (est.) | Saving applied |
| --- | --- | --- | --- | --- |
| Key points | 0.5 on average | Passage text | about 4,000 | Cached per passage and shared for YouTube media; prefetched while Blind plays |
| Gist grade | 1 | Key points, passage text, gist | about 4,000 | Fixed output schema, so no retries for format |
| Round feedback | 3 | Measures and flagged words only (no audio, no full text) | about 1,500 each | Small, fast model is enough |
| Suggestions | 1 | Pattern list and measure deltas | about 2,000 | One call for all three rounds |
| **Total** | **about 5.5** |  | **about 14,000** |  |

### 7.2 Quota-saving mode

When a provider's remaining daily quota drops below 25%, the gateway switches round feedback for rounds 1 and 2 to **template feedback**: deterministic sentences generated from the measures (for example "Your timing lagged the speaker by about 0.4 s on average; the biggest gaps were on 'could have' and 'a lot of'"). Round 3 and the suggestions still use AI. This drops a session from about 5.5 to about 2.5 calls. The learner always gets feedback; only the wording style changes.

### 7.3 Other savings

- **Structured output** (JSON schema mode where the provider supports it) and temperature 0, so outputs are valid and stable on the first try.
- **Token budgets per task**: input is trimmed to the budget before sending, and the output length is capped.
- **Request coalescing**: if two learners trigger key points for the same shared passage at once, a job lock makes the second wait for the first result instead of calling again.
- **Provider choice by task**: key points and gist grading need a stronger model; round feedback works with the smallest one. The gateway configuration sets the provider per task, not only per role.
- **Quota telemetry**: calls and tokens per provider per day are counted, with an alert at 75% use.

## 8. Data layer

PostgreSQL alone handles data, queue, rate counters and change notifications through stage 1, which is possible because hot data is stored compactly and every frequent query has an index made for it.

### 8.1 Compact storage

- **Packed transcript words.** Instead of one row per word, a passage transcript stores parallel arrays: `words text[]`, `start_ms int4[]`, `end_ms int4[]`, `confidence int2[]` (0 to 1000) and `sentence_starts int4[]`. A 3-minute passage (about 450 words) takes roughly 6 KB after PostgreSQL's built-in compression, against roughly 60 KB as rows with indexes (est.). Marks refer to word positions in these arrays.
- **Passage cache keyed by range.** `passage_transcripts` and `reference_profiles` are keyed by (media object, `int4range` of milliseconds) with a GiST index, so "is any cached range overlapping this passage?" is one indexed query.
- **Heartbeats update in place.** A Blind heartbeat updates one row (`last_position_ms`, `last_heartbeat_at`). The table uses a fill factor of 70 so these become in-page (HOT) updates with no index churn. Only voids are logged.
- **Grades as JSONB.** Measures, word labels and comparisons are read whole and never queried field by field, so one JSONB column per result avoids dozens of narrow tables.

### 8.2 Indexes for the hot queries

| Query | Index |
| --- | --- |
| A learner's library, newest first | `contents (user_id, created_at DESC)` |
| A learner's sessions | `practice_sessions (user_id, updated_at DESC)` |
| One open attempt per mode | partial unique `attempts (session_id, mode) WHERE status = 'active'` |
| Marks and rounds of a session | `marks (session_id)`, unique `shadow_rounds (session_id, round)` |
| Card list | `cards (user_id, created_at DESC)` |
| Shared media lookup | unique `media_objects (fingerprint)` |
| Cached passage lookup | GiST on `(media_object_id, range)` |
| Expiry sweeps | `media_objects (last_used_at)`, `shadow_rounds (created_at)` |

All list endpoints use keyset pagination on these indexes, never `OFFSET`.

### 8.3 Connections, partitions and summaries

- **Pooling.** Each API process keeps a small async pool (about 5 connections); each worker process 2. When there is more than one API instance, or the managed database limits connections, a transaction-mode pooler (PgBouncer or the provider's built-in pooler) sits in front.
- **Partitioning.** `ai_calls` and any audit log are partitioned by month; partitions older than 90 days are dropped, which is instant compared with deleting rows.
- **Summary tables.** Learner trends (scores over sessions) are maintained in `learner_trends` when each grade is written, so the trends page never scans grade history.

### 8.4 Caching (no Redis until stage 2)

| Layer | What is cached | How |
| --- | --- | --- |
| Browser | Contents, transcripts after unlock, cards | TanStack Query plus HTTP `ETag`; unchanged data answers `304 Not Modified` |
| API process | Prompt templates, configuration, signed URLs per asset (reused until 80% of their lifetime) | In-memory LRU |
| Database | Shared passages, profiles, key points | The tables above act as a persistent cache |
| Edge | Static web app files with content-hashed names | CDN, cached for a year |

Rate limits run at the edge for IP-based limits and in an `UNLOGGED` PostgreSQL counter table for per-learner limits. Redis is introduced at stage 2, when several API instances need fast shared counters and session lookups.

## 9. Real-time updates and client efficiency

Live updates use PostgreSQL's built-in notifications instead of a message broker, and the client sends small, infrequent requests and loads only the code for the current mode.

### 9.1 Live updates without a broker

1. When a job finishes, the worker runs `NOTIFY user_events` with a tiny payload: user id, event type and resource id. The notification is sent in the job's own transaction, so PostgreSQL delivers it only on commit.
2. Each API process holds **one** listening database connection and keeps an in-memory map of open Server-Sent Events streams by user.
3. The API forwards the event to that user's streams; the browser then fetches the resource. Payloads carry ids only, never data, so they stay far below PostgreSQL's notification size limit.
4. Streams send a comment line every 25 s so proxies keep them open. On reconnect the browser sends `Last-Event-ID` and refetches anything still pending. Event ids are \<process id>-\<sequence>, and each process keeps a short replay buffer per user (the last 50 events for 2 minutes). A reconnect to the same process within that buffer gets the missed events replayed; any other reconnect gets one resync event, and the browser refetches every resource it still shows as pending. The stream is GET /api/v1/events.

An async Python server holds thousands of idle streams per process, far beyond stage 1 needs. At stage 2 the notification source moves to Redis publish and subscribe, with no client change.

### 9.2 Blind heartbeats

- One heartbeat every 5 s, about 0.2 requests per second per learner in Blind.
- The service locks the attempt row and applies the pure heartbeat judge in one transaction, then writes its decision. Position is measured against an anchor clock (at most 1.5 s ahead and 6 s behind), not by accumulating tolerances between beats; during an unfinished listen, a hidden page or a seek voids; more than 15 s without a beat voids only when no eligible interruption is reported. A first eligible interruption moves the anchor to `max(passage start, stop − 3 s)` and records the resume; a second interruption or device pause of 5 s or more records `interrupted` ([ADR 0024](../adr/0024-blind-heartbeats-resume-and-attempt-bound-media.md)).
- Network buffering is not cheating: the player reports buffering and the server moves its anchor clock later, up to 20 s per listen; the one resume gets a fresh 20 s, at most 40 s per attempt. After 10 s without an answered beat the player stops and reports a network interruption when contact resumes ([ADR 0024](../adr/0024-blind-heartbeats-resume-and-attempt-bound-media.md)).
- In-app navigation including Browser Back must warn before leaving an unfinished listen; leaving the completed listen's gist form preserves it ([ADR 0033](../adr/0033-design-review-policy-resolutions.md)). On `pagehide`, visibility changing to hidden and in-app unmount, the browser reports leaving with `fetch(..., {keepalive: true})` so it can include the required `X-CSRF-Token` header; `navigator.sendBeacon` cannot send it ([ADR 0024](../adr/0024-blind-heartbeats-resume-and-attempt-bound-media.md)).
- Once the attempt starts, the player preloads the whole passage (`preload="auto"`, about 1.5 MB for 3 minutes) so buffering is rare.

### 9.3 Client weight and traffic

| Technique | Effect |
| --- | --- |
| Route-based code splitting; each mode and the waveform library load only when used | Initial JavaScript under 200 KB compressed (target) |
| Content-hashed static files on a CDN | Repeat visits load from cache |
| Waveform peaks from the server (section 6); passage picker draws SVG bars with accessible sliders, without wavesurfer.js; storage CORS allows GET from the web origin ([ADR 0026](../adr/0026-passage-picker-drawn-from-server-peaks.md)) | No audio decoding on phones |
| Dictation autosave: immediate durable local copy (the one-second save target), server save starts 2 s after the last edit when connected ([ADR 0033](../adr/0033-design-review-policy-resolutions.md)), one request at a time; stale differing drafts get 409 `draft_conflict`, identical resend succeeds; reconnect or `Retry-After` retries preserve unsent work ([ADR 0025](../adr/0025-dictation-drafts-autosave-and-passage-player.md)) | Few requests, no lost text when offline, no silent overwrite between tabs |
| Recordings uploaded straight to storage right after each round (about 0.2 MB) | 1 to 2 s on a typical mobile connection; the API never handles audio bytes |
| 64 kbit/s audio playback | About 8 KB per second, workable on slow mobile networks |

## 10. Scaling path

Growth is handled in four stages, and each move is triggered by a measured gate rather than a guess; the code does not change between stages, only where containers run and which managed services back them.

&#91;embedded content: scaling path · 4 stages, 3 measured gates\]

Why this order: speech compute runs out first (section 2), so the first paid spend goes to speech workers. The database comes next, then shared caches. Splitting the monolith comes last and only for an organisational or scaling reason that a bigger machine cannot solve.

## 11. Reliability

Every failure degrades a feature rather than the practice session: a learner can always continue the current step, and anything that failed is retried or retried on request.

### 11.1 Failure modes

| Failure | Detected by | System behaviour |
| --- | --- | --- |
| Worker crashes mid-job | Job lock expires | Job is retried; handlers are idempotent (upsert by natural key), so a retry never duplicates results |
| A job keeps failing ("poison job") | Attempt count | After 3 to 5 attempts (per job type) it is marked failed, shown in the admin view, and the learner sees a retry action |
| Media worker overloaded | Interactive queue wait over 30 s | Background jobs paused, new intake throttled, learners see an estimated wait |
| AI provider down or out of quota | Gateway errors, quota counters | Next provider; then template feedback; then "feedback delayed" with automatic retry |
| YouTube changes break the downloader | Intake failure rate alert | Downloader updated automatically each day; learner offered upload instead |
| Database unavailable | Health checks | API returns `503` with `Retry-After`; the browser keeps drafts and marks locally and resends; workers pause |
| Object storage unavailable | Upload or URL errors | Playback and recording show retry; jobs retry with backoff |
| Live event stream drops | Browser | Falls back to polling every 5 s until the stream reconnects |
| The stage 0 server is lost | External uptime monitor | Rebuild on any host from container images and the managed database (RTO below) |

### 11.2 Objectives

| Objective | Stage 0 | Stage 1 and later |
| --- | --- | --- |
| Availability of practice screens | 99.5% per month | 99.9% per month |
| Data loss on disaster (RPO) | up to 24 h (nightly dump plus managed backups) | minutes (point-in-time recovery) |
| Time to restore (RTO) | 4 h | 1 h |
| Learner text lost on refresh or disconnect | none | none |

### 11.3 Idempotency everywhere

- Jobs carry a unique key (for example `grade_round:<round id>`), so the same work is never queued twice.
- Submissions carry an `Idempotency-Key`; a repeated request returns the first result.
- Every result write is an upsert on its natural key.

## 12. Benchmarks and architecture changes

The estimates above become commitments only after six benchmarks, run on the actual stage 0 server in the first build milestone.

### 12.1 Benchmarks to run

| # | Benchmark | Decides | Pass if |
| --- | --- | --- | --- |
| B1 | Transcription speed and word accuracy, 3 model sizes, on 20 passages | Model size; the 150-learner estimate | About 1 core-second per audio-second or better, word error rate within threshold |
| B2 | Forced alignment speed on creator captions | Caption path cost | About 0.2 core-second per audio-second or better |
| B3 | Shadow round analysis, end to end, on 30 recordings | Round latency target | Scores in under 50 s at p95 with no queue |
| B4 | Filler recall of the disfluency-keeping pass | Whether filler counts ship as "estimate" | At least 80% of teacher-marked fillers found |
| B5 | Load test: 15 requests per second mixed traffic plus 20 Blind learners sending heartbeats | API and database headroom | p95 within section 1 targets at under 30% CPU |
| B6 | AI calls per day available on the chosen free tiers | Whether quota-saving mode is on by default | Enough for the stage's daily calls (section 2.3) |

### 12.2 Changes to the architecture document

This design refines the [ListenUp Software Architecture](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13) in five places, which should be applied to it:

1. **Shared media.** Add `media_objects` (one per YouTube video or per-learner upload); `contents` becomes the learner's reference to it.
2. **Packed transcripts by passage.** Replace the `transcript_words` table with `passage_transcripts` holding word arrays, keyed by media object and millisecond range.
3. **Reference profiles.** Add `reference_profiles` per passage, computed at `transcribed` time and used by every Shadow round.
4. **No stored analysis audio.** Drop the stored `analysis.flac`; workers decode it on demand.
5. **Queues.** Replace the two queues (`default`, `media`) with the four in section 4, and add quota-saving template feedback to the grading module.
