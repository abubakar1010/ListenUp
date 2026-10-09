Source: https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13 · Exported 2026-10-09

# ListenUp Software Architecture

Oct 2, 2026 · @Md. Ebrahim Hossen

## 1. Summary

ListenUp is built as a **modular monolith in Python (FastAPI) with separate background workers, a React web client, PostgreSQL and S3-compatible object storage**, all packaged as containers so it can run at zero cost now and move hosts or AI vendors later without a rewrite.

This document turns the PRD and SRS into a buildable design. Requirement IDs (FR-BL-1, NFR-AI-7 and so on) refer to the SRS.

### 1.1 Architecture drivers

These few requirements shape the design more than any others:

| Driver | Why it matters | Where it is handled |
| --- | --- | --- |
| Rules must be enforced, not suggested (Blind lock, step order, two cards) | A client-only lock is trivially bypassed | Server-side session state machine and attempt integrity checks (4, 5.2) |
| Heavy media and AI work (download, transcription, speech grading) | Minutes of CPU per job; must never block the practice screen | Job queue and dedicated workers (3, 6) |
| Free first, no vendor lock-in for AI | Free tiers change and run out; vendors must be swappable | AI adapter layer with config-driven providers and fallbacks (7) |
| Voice recordings and learner text are personal data | Free AI tiers often train on inputs | Provider eligibility rule, self-hosted fallback, deletion cascade (7, 12) |
| Speech science is Python-first (Whisper, forced alignment, phoneme models, Praat) | Using the same language end to end avoids a second backend stack | Python for API and workers (2) |
| Solo or small team, zero budget | Few moving parts, cheap to operate | One codebase, one database, one queue, container deploy (2, 11) |

### 1.2 Principles

1. **One backend, clear modules.** A modular monolith, not microservices. Modules talk through their public service interfaces only, so any one can be split out later.
2. **The server owns the truth.** Session state, step gating, Blind timing and card limits live in the backend; the client renders them.
3. **Everything slow is a job.** Requests return in milliseconds; downloads, transcription and grading run in workers and report progress.
4. **Ports and adapters for anything external.** YouTube, AI providers, storage and email sit behind interfaces with swappable implementations.
5. **Standards over services.** PostgreSQL, the S3 API, OpenID Connect, OpenAPI and Docker, so every hosted piece has a self-hosted or competing equivalent.
6. **Deterministic where possible, AI where needed.** Dictation scoring and timing measures are plain algorithms; AI writes explanations and judges meaning.
7. **Fail soft.** A failed grading job never blocks the plan; the data is kept and the job can be retried.

## 2. Technology stack

The stack is Python on the server, TypeScript in the browser, and only open standards for data and storage. Every choice below is free and open source unless marked as a hosted service.

| Layer | Choice | Why | Alternative considered |
| --- | --- | --- | --- |
| Web client | React + TypeScript, built with Vite as a single-page app | Rich media UI, large ecosystem, deploys as static files to any CDN | Next.js: server rendering is not needed for a logged-in practice app |
| Client data and routing | TanStack Query, React Router | Caching, retries and background refresh of server state | Redux: more code for the same result |
| Styling | Tailwind CSS with design tokens as theme variables and a small component library | Fast, consistent, no runtime cost | CSS modules |
| Media playback | Native HTML audio and video elements with our own controls | Only our own controls can enforce Blind (no pause, no seek) | YouTube embedded player: cannot be locked reliably |
| Waveform and segment picking | wavesurfer.js | Passage and Shadow segment selection on a waveform | Custom canvas drawing |
| Recording | Browser MediaRecorder API (Opus in WebM or MP4) | Built in, no plugin | Recorder libraries add little |
| API | Python 3.12, FastAPI, Pydantic v2 | Typed, fast, generates OpenAPI; same language as speech tooling | Node.js (NestJS): would need a second backend language for workers |
| Database access | SQLAlchemy 2 and Alembic migrations written as SQL, with models mirrored for alembic check | Mature, typed, portable across PostgreSQL hosts | Raw SQL |
| Background jobs | Procrastinate (PostgreSQL-backed queue) in separate worker processes | No extra infrastructure; jobs commit in the same transaction as data | Celery or Dramatiq with Redis, when volume needs it |
| Database | PostgreSQL 16 | Relational data, JSONB for AI results, row locking for the queue | MySQL |
| Object storage | Any S3-compatible store; SeaweedFS locally | Standard API, every cloud offers it | Local disk: does not scale past one server |
| Media tools | yt-dlp, ffmpeg and ffprobe | Download, convert, cut snippets, validate uploads | Hosted transcoding: cost and lock-in |
| Speech processing (self-hosted) | faster-whisper, wav2vec2 forced alignment, a wav2vec2 phoneme model, Praat via Parselmouth | Free, runs on CPU, covers transcription, word timing, sound-level scoring and pitch | Hosted APIs only: quotas and privacy limits |
| Auth | Built into the API: Argon2id password hashes, server sessions in httpOnly cookies, Google sign-in via OpenID Connect (Authlib) | No per-user fees, no lock-in, accounts stay in our database | Hosted auth (Clerk, Auth0, Supabase Auth): lock-in and limits |
| Live job status | Server-Sent Events, with polling as fallback | One-way updates are all that is needed; works through proxies | WebSockets: more moving parts |
| API contract | OpenAPI from FastAPI, TypeScript client generated from it | Client and server types never drift | Hand-written client |
| Email | SMTP behind an interface | Any provider works, including free tiers | Provider SDK |
| Observability | Structured JSON logs, OpenTelemetry traces, an error tracker behind its SDK | Vendor-neutral | Provider-specific agents |
| Tooling | uv (Python), pnpm (JavaScript), Ruff, mypy, ESLint, Prettier | Fast, strict, reproducible | pip, npm |
| Tests | pytest, Vitest, Playwright | Unit, component and browser tests | Cypress |
| Packaging and CI | Docker, Docker Compose, GitHub Actions | Same images locally and in production; free CI for the repo | Platform-specific buildpacks |

## 3. System containers

The system is five deployable parts of our own (web app, API, two worker pools, a self-hosted LLM) plus PostgreSQL and object storage; the browser talks to the API, and to storage only through signed URLs.

&#91;embedded content: containers · 5 of ours, 2 data stores, 3 outside services\]

| Container | Runs | Scales by |
| --- | --- | --- |
| Web app | Static files on a CDN | CDN, no servers |
| API | FastAPI under Uvicorn, stateless | More API containers |
| Worker: default | Lanes 3 `ai` and 4 `background`: key points, gist grades, round feedback (AI text calls), email, deletion, retention sweeps, scheduled clean-up | More default workers serving lanes 3 and 4 |
| Worker: media | Lanes 1 `speech-interactive` and 2 `intake`: yt-dlp, ffmpeg, passage transcription, alignment, reference profiles, speech assessment (CPU heavy) | More media workers serving lanes 1 and 2, or a bigger machine |
| Self-hosted LLM | Ollama or llama.cpp with a small open model, the always-free text AI fallback | Optional; can be turned off when a hosted tier is used |

The API never runs anything slow. It writes the job to the PostgreSQL queue in the same transaction as the data change, so a job is never lost or run for data that was rolled back.

## 4. Backend modules

The backend is one Python package split into business modules with strict boundaries; the API process and the worker processes load the same code, so a rule is written once and enforced everywhere.

### 4.1 Modules

| Module | Owns | Key responsibilities |
| --- | --- | --- |
| `identity` | Users, login sessions, linked Google accounts, consents | Register, sign in, password reset, account deletion (orchestrates deletion in every other module) |
| `content` | Shared media objects (reference-counted), learners' content items, uploads | YouTube and upload intake, reuse of a YouTube video already in the system, validation, passage selection, signed media access |
| `transcript` | Passage transcripts (packed word arrays per media object and time span), reference profiles, per-learner corrections | Caption import, passage transcription and alignment jobs, reference profiles for Shadow, transcript corrections |
| `practice` | Practice sessions, steps, attempts | Builds the 4 or 5 step plan, the session state machine, step gating, entry-choice lock, skips |
| `blind` | Blind attempts, heartbeats, gists | Locked playback rules, integrity checks, gist submission |
| `dictation` | Dictation attempts, drafts, word diffs | Draft autosave, deterministic word-level scoring, mark candidates |
| `review` | Marks | The Transcript step: creating, tagging and listing marks |
| `cards` | Cards, card snippets | Two-card limit, snippet cutting, card review |
| `shadow` | Segments, rounds, recordings | Segment choice (60 to 90 seconds, or the whole passage when it is 30 to 60 seconds), three-round rules, recording uploads |
| `grading` | Key points, gist grades, round grades, comparisons | Orchestrates gist and Shadow grading, computes final scores, repeated-mistake detection, quota-saving template feedback when AI quota runs low |
| `ai` | Provider registry, quotas, AI call log | The adapter layer (section 7); knows nothing about learners or modes |
| `library` | Nothing (read-only views) | Lists across content, sessions, cards and trends |
| `notifications` | Email templates | Verification and reset emails through an SMTP adapter |
| `admin` | Usage reports, takedown records | Quota and cost view, abuse and takedown handling |

Shared technical code (configuration, database, storage, queue, event stream, logging, security helpers) lives in a `platform` package that every module may use.

### 4.2 Inside a module

Every module has the same layers, and dependencies only point inward:

- `api.py`: FastAPI routes. Parses input, checks ownership, calls the service. No business logic.
- `service.py`: the module's **public interface**. Transactions, orchestration, enqueueing jobs.
- `domain/`: pure rules with no input or output (state machine, scoring, limits). Fully unit-tested.
- `repository.py` and `models.py`: SQLAlchemy persistence for this module's tables only.
- `schemas.py`: Pydantic request and response models.
- `jobs.py`: background job handlers that run in the workers.

### 4.3 Dependency rules (checked in CI with import-linter)

1. A module may call another module only through that module's `service.py`. No reaching into another module's tables, models or repository.
2. `practice` never imports a mode module. Mode modules ask `practice` for permission (`require_step(session, Step.BLIND)`) and report completion (`complete_step(...)`).
3. `grading` depends on `ai`; `ai` depends only on `platform`. No module other than `grading` and `transcript` calls `ai`.
4. `domain/` packages import nothing from frameworks, the database or the network.
5. Cross-module side effects that can wait (for example "transcript ready" starting key-point extraction) go through the job queue, inside the same database transaction as the change that caused them.

These rules keep each module replaceable and make a later split into separate services a packaging change, not a redesign.

## 5. Key flows

Four flows carry most of the product's risk; each is designed so the server decides the outcome and slow work runs as jobs.

### 5.1 Content intake

**YouTube link**

1. The client sends the URL. The API looks up the media object by its fingerprint (`youtube:<video id>`). If the video is already in the system, the API creates the learner's content item pointing to it and adds one to its reference count: a `playable` video is ready at once, with its cached passage transcripts, reference profiles and key points, and one whose playback file has expired is downloaded again from step 3. Otherwise the API creates a `pending` media object and the content item, and enqueues `content.fetch_metadata` on the `intake` lane.
2. A media worker reads metadata with yt-dlp. Private, age-restricted, live or over-length videos are rejected with a clear reason.
3. The worker downloads the best audio (and a 480p video stream for video clips) and stores the source file.
4. ffmpeg produces one stored file, the **playback file** (AAC in MP4, H.264 for video), and the source download is deleted; the media object becomes `playable`. Analysis audio (16 kHz mono) is never stored: each speech job decodes it from the playback file into worker scratch space and deletes it when the job ends.
5. When a learner chooses a passage, it is transcribed unless a cached passage transcript of that media object already covers its span; only the missing part is processed. If the video has creator-written captions, they are imported and force-aligned to the audio to get word times. Auto-generated captions are ignored, because they are often worse than our own transcription.
6. Otherwise the transcription role produces words with times.
7. The words are stored as a passage transcript (packed word arrays keyed by media object and millisecond span), shared by every learner on that passage, and the passage's reference profile for Shadow is computed and stored once. The client gets an event as the passage becomes `transcribed`, then `profiled`.

**File upload**

1. The client asks the API for a signed upload URL and uploads straight to object storage, so large files never pass through the API. The API refuses files over 500 MB and uploads that would take the account over 2 GB of stored uploads.
2. The client confirms the upload. A worker checks the real file type, streams and duration with ffprobe (the file name and browser-reported type are not trusted).
3. The upload becomes its own media object, fingerprinted per learner (upload:\<user id>:\<sha256>) and never shared with other learners. Steps 4, 5, 6 and 7 above follow, without the caption import.

### 5.2 Practice session and Blind integrity

The session state machine in `practice/domain` decides which step is open. A client cannot skip ahead because every mode endpoint calls `require_step` first. The transcript endpoint itself is gated: it returns text only once the session has reached the Transcript step (FR-TX-5).

Blind is enforced on the server, not only by hiding buttons:

1. Starting Blind creates an attempt with a server start time and returns a **media URL valid only for that attempt** and only for slightly longer than the passage.
2. The player has no pause, seek or speed controls. Every 5 seconds it sends a heartbeat: playback position, playing state and page visibility.
3. The server checks that position moves forward in step with server time (within a tolerance), that heartbeats keep arriving, and that the page stays visible.
4. Leaving the page (`visibilitychange`, `pagehide`), a reload or a backward jump voids the attempt. Missing heartbeats from an interruption the learner did not cause (a network stall, or a device or OS pause under 5 seconds) allow one resume per attempt, started automatically 3 seconds after the audio is ready, from 3 seconds before the last recorded position, with no option to stay paused; a second interruption voids the attempt.
5. The gist is accepted only if enough server time has passed to hear the whole passage and the last position is near the end.

This stops honest learners from slipping and makes cheating visible. It cannot stop someone recording the audio with another device, and it does not try to.

### 5.3 Dictation scoring

Scoring is a pure, deterministic function in `dictation/domain`, with no AI:

1. **Normalize** both texts: lower case, strip punctuation, unify apostrophes, expand contractions ("could've" and "could have"; "'d" and "'s" after a pronoun match either full form), reduce numbers in digits or words to one key ("15" and "fifteen", "21st" and "twenty-first"), and map British spellings to American ones from a curated table. Punctuation never changes a score.
2. **Align** words with a weighted edit-distance alignment (insert, delete, substitute). A substitution is a spelling slip within a limit that scales with word length (three letters or fewer: a swapped or doubled letter only; four letters: one edit; five or more: two edits), and so is a word typed joined or split ("alot", "every one"); otherwise it is a wrong word. Long passages are first anchored on common start and end and on tokens unique to both texts (patience diff).
3. **Classify** each reference word as correct, spelling slip, wrong or missing, plus extra words. Accuracy = correct words / reference words, with spelling slips counted as correct (one constant, SPELLING\_SLIPS\_COUNT\_AS\_CORRECT; the stored diff records which rule applied). Slips are still reported separately and are not mark candidates.
4. Every wrong or missing word becomes a **mark candidate** carrying its audio time from the word timestamps.

If the learner believes the reference transcript is wrong at some word, they can dispute that word from the diff. The corrected reference is saved (FR-TX-4) and the attempt is re-scored. This resolves the conflict between hiding the transcript and letting learners fix it.

### 5.4 Gist grading

1. When a session's passage is first used, a job asks the text AI role to extract 3 to 6 key points (one main idea, the rest supporting). They are cached per media object and passage range, so every learner on that passage is graded against the same reference.
2. On gist submission a `grading.grade_gist` job sends the key points, the passage text and the gist (as clearly delimited data) with the versioned `grade_gist` prompt.
3. The model must return a fixed structure: per-dimension scores, which key points are covered, any wrong claims, and feedback text. The structure is validated; anything out of range is rejected and retried.
4. **Our code computes the overall score** from the dimension scores and the rubric weights, so the weighting never depends on model arithmetic.
5. On repeated failure, or when no grade is ready 30 seconds after submission, the grade is stored as `unavailable` with a retry action, and the learner continues.

## 6. Shadow grading pipeline

Shadow grading is a chain of media-worker jobs in which speech models and plain code produce every number, and the text AI is used only to turn those numbers into feedback and suggestions.

&#91;embedded content: Shadow grading pipeline · 6 steps per round, 3 after round 3\]

**How each measure is computed (all comparisons are against the original clip, not a fixed "native" standard):**

| Measure | Computation |
| --- | --- |
| Rhythm and timing | Word onsets of learner and original from forced alignment, compared with dynamic time warping; speech-rate ratio; pause positions and lengths |
| Pronunciation | Goodness-of-pronunciation score per sound from a phoneme model, averaged per word |
| Accent | Vowel quality, word stress and pitch contour (Parselmouth) compared with the original speaker. Marked experimental until it passes the golden set and fairness checks. Shown as guidance ("compared with this speaker") and left out of the overall round score, which weights the other measures equally |
| Articulation | Dropped, merged or unclear sounds, especially word endings and linking, from low-confidence or missing phones |
| Fluency | Hesitations, restarts and long pauses from the speech timeline |
| Filler words | Count and rate per minute from a transcription pass that keeps disfluencies |
| Completeness | Share of segment words found by the alignment |

**Patterns (step 8)** are rule-based over sound-level errors: for example final consonant deletion, one sound regularly replaced by another, or stress on the wrong syllable. A pattern needs evidence in at least two rounds. **Suggestions (step 9)** receive only the pattern list and the measures, and must return at most three items, each tied to a pattern.

The echo check in step 2 compares the recording with the original audio; if the original leaked through speakers, the round is flagged and the learner is asked to use headphones.

## 7. AI adapter layer

All AI goes through four typed interfaces ("ports") and one gateway that adds quotas, fallbacks and validation, so a provider can be swapped by editing configuration and the rest of the code never knows which vendor answered.

### 7.1 Ports

| Port | Method | Returns |
| --- | --- | --- |
| `TranscriptionPort` | `transcribe(audio, language="en")` | Words with start and end times and confidence |
| `AlignmentPort` | `align(audio, text)` | Word and sound (phone) timings for a known text |
| `SpeechAssessmentPort` | `assess(recording, reference_text, reference_audio)` | Per-word and per-sound scores, timing, pauses, fillers, pitch contour |
| `TextAIPort` | `generate(task, input, output_schema)` | A validated Pydantic object of the requested schema |

The ports are Python Protocols in `ai/ports.py` with vendor-neutral input and output types. Providers implement them in `ai/providers/`.

### 7.2 The gateway

Modules never call a provider directly; they call `ai.gateway`, which for every request:

1. Looks up the role's **ordered provider list** in configuration (`ai.yaml` per environment, secrets from environment variables).
2. Skips providers that are **not eligible** for the data: each provider declares `trains_on_inputs`, and any provider that does is never sent recordings, transcripts or gists (NFR-AI-7).
3. Checks the provider's **remaining free quota** (counters per day and month in PostgreSQL) and its rate limit.
4. Calls it with a timeout, retrying network errors with backoff.
5. **Validates** the result against the output schema and value ranges.
6. On failure, quota exhaustion or invalid output, moves to the next provider. If none is left, it raises `AIUnavailable`, which callers turn into "feedback delayed" or "unavailable".
7. **Logs** provider, model, version, prompt version, latency, units used and outcome to `ai.calls`, without the learner's identity.

### 7.3 Prompts and outputs

- Prompts live in `ai/prompts/<task>/<version>.md` next to a JSON Schema for the output. Tasks in the MVP: `extract_key_points`, `grade_gist`, `shadow_feedback`.
- Every stored result records the task and prompt version, so old and new results can be told apart.
- Learner text is always passed inside a delimited data block, and the instructions say to treat it as data. Scores the product shows are computed by our code from the model's dimension scores, never taken as free text.
- Text AI providers are written against the **OpenAI-compatible chat API** where possible. Many hosted services and local servers (Ollama, llama.cpp, vLLM) speak it, so one adapter covers many vendors.

### 7.4 Evaluation before any switch

`ai-evals/` holds golden sets: about 50 teacher-graded gists and about 50 teacher-graded Shadow recordings. A command runs any provider against them and reports agreement with the teacher, mean error and consistency over three runs. A provider goes live only when it meets the thresholds (NFR-AI-6). CI runs a small smoke subset on every change to prompts or providers.

### 7.5 Starting providers (MVP, zero cost)

| Role | Default (self-hosted, free) | Optional hosted provider |
| --- | --- | --- |
| Transcription | faster-whisper on CPU, English model, int8 | A hosted Whisper free tier, only if its terms exclude training |
| Alignment | wav2vec2 CTC forced alignment | None needed |
| Speech assessment | Local pipeline: alignment, phoneme model scoring (goodness of pronunciation), Parselmouth pitch and intensity | A hosted pronunciation assessment free tier for comparison, only if its terms allow |
| Text AI | A hosted LLM free tier whose terms exclude training on inputs | A small open model on our own server (Ollama or llama.cpp) as the always-available fallback |

Free tiers and their terms change often, so the hosted entries are chosen at build time after checking current terms, and recorded in an ADR. Model sizes and CPU timings must be benchmarked on the chosen server before launch.

## 8. Data model

All learner data lives in PostgreSQL tables owned by one module each, and every learner-owned row carries `user_id`, so ownership checks and account deletion are a single rule.

**Conventions:** primary keys are UUIDv7 (sortable by time); audio times are integer milliseconds; timestamps are UTC; AI outputs are stored as JSONB next to the provider, model and prompt version that produced them.

The table below is a summary of the main tables, named by schema; the [ListenUp Database Design](https://claude.ai/code/artifact/ba05f7b3-f881-41e5-86d6-dcb94a509644) holds the full schema, with DDL, constraints, indexes and row-level security.

| Table | Module | Key columns |
| --- | --- | --- |
| `identity.users` | identity | id, email, password\_hash, email\_verified\_at, status (active, pending\_deletion, deleting), deletion\_scheduled\_at, created\_at |
| `identity.auth_sessions` | identity | id, user\_id, token\_hash, expires\_at, user\_agent |
| `identity.oauth_accounts` | identity | provider, subject, user\_id |
| `identity.consents` | identity | user\_id, kind (terms, privacy, voice\_recording), version, granted\_at, withdrawn\_at |
| `content.media_objects` | content | id, fingerprint (unique: YouTube video id, or upload hash per learner), source (youtube, upload), uploaded\_by, duration\_ms, status, playback\_key, video\_key, peaks\_key, ref\_count, last\_used\_at |
| `content.contents` | content | id, user\_id, media\_object\_id, title, keep\_video; the learner's reference to a media object, once per library |
| `content.passage_transcripts` | transcript | id, media\_object\_id, span (ms range), origin (creator\_captions, generated), status, packed arrays words, start\_ms, end\_ms, confidence, sentence\_starts, provider\_info |
| `content.reference_profiles` | transcript | passage\_transcript\_id, model\_version, phones, pitch\_cents, intensity\_db, stats; computed once per passage when it is transcribed, read by every Shadow round |
| `content.transcript_corrections` | transcript | user\_id, passage\_transcript\_id, word\_index, corrected\_text |
| `practice.sessions` | practice | id, user\_id, content\_id, passage (ms range), entry (blind, dictation, both), current\_step, entry\_locked\_at, status, version |
| `practice.session_steps` | practice | session\_id, step, position, status (locked, open, done, skipped), completed\_at |
| `practice.attempts` | practice | id, session\_id, mode (blind, dictation), status (active, submitted, voided), started\_at, finished\_at |
| `practice.blind_attempts` | blind | attempt\_id, media\_token\_hash, last\_position\_ms, last\_heartbeat\_at, resume\_count (0 or 1), void\_reason, gist\_text |
| `practice.dictation_attempts` | dictation | attempt\_id, draft\_text, submitted\_text, scoring\_status, diff (JSONB), accuracy |
| `practice.marks` | review | id, session\_id, word\_from, word\_to, at\_ms, tag, note, source (dictation, manual), status |
| `practice.cards` | cards | id, user\_id, session\_id, slot (1, 2), mark\_id, media\_object\_id, written\_form, heard\_form, snippet\_key |
| `practice.shadow_segments` | shadow | session\_id, span (60 to 90 s, or the whole 30 to 60 s passage), chosen\_by, locked\_at |
| `practice.shadow_rounds` | shadow | id, session\_id, round (1 to 3), transcript\_shown, status, recording\_key |
| `grading.key_points` | grading | id, media\_object\_id, span, prompt\_version, points (JSONB) |
| `grading.gist_grades` | grading | attempt\_id, status, dimension\_scores, overall, level, covered\_points, wrong\_claims, feedback, provider\_info |
| `grading.round_grades` | grading | round\_id, status (pending, scored, ready, unavailable), measures (JSONB), word\_labels (JSONB), feedback, feedback\_mode (ai, template), speech\_info, text\_info |
| `grading.shadow_comparisons` | grading | session\_id, status, deltas, repeated\_mistakes, patterns, suggestions (JSONB) |
| `ai.calls` | ai | id, role, task, provider, model, prompt\_version, latency\_ms, input\_units, output\_units, outcome, created\_at (partitioned by month) |
| `ai.quota_usage` | ai | provider, period (day, month), period\_start, calls, units |

Job tables come from the queue library's own SQL (Procrastinate, vendored and applied by migration 0003) in the same database, in their own procrastinate schema, which the database's search path includes.

**Database rules enforced by constraints, not only code:** one open attempt per session and mode (partial unique index); at most two cards per session (a slot of 1 or 2, unique per session); `round` between 1 and 3 and unique per session; Shadow segment length between 60,000 and 90,000 ms; deleting a user cascades to every owned row.

### 8.1 Object storage layout

One private bucket. Media files are keyed by media object, because one YouTube video serves every learner who adds it; a learner's own files are grouped by user, so deleting an account removes that prefix plus the learner's upload media objects:

```
media/{media_object_id}/source.{ext}      deleted after conversion
media/{media_object_id}/playback.mp4
media/{media_object_id}/video.mp4         only when video is kept
media/{media_object_id}/peaks.json
users/{user_id}/sessions/{session_id}/shadow/round-{n}.webm
users/{user_id}/cards/{card_id}.m4a
```

The bucket is never public. The browser only ever receives short-lived signed URLs issued after an ownership check.

## 9. API design

The API is JSON over HTTPS under `/api/v1`, described by the OpenAPI schema FastAPI generates; the web client's TypeScript types are generated from that schema on every build.

### 9.1 Conventions

- **Auth:** a server session in an `httpOnly`, `Secure`, `SameSite=Lax` cookie. State-changing requests also carry a CSRF token header.
- **Errors:** RFC 9457 problem details (`type`, `title`, `status`, `detail`, plus a stable `code` such as `step_locked` or `card_limit_reached`).
- **Idempotency:** submissions (gist, dictation, round complete) accept an `Idempotency-Key` header, so a retried request never creates a second attempt.
- **Pagination:** cursor based (`?cursor=…&limit=…`).
- **Rate limits:** per user and per IP on login, intake and grading endpoints.
- **Live updates:** `GET /api/v1/events` is a Server-Sent Events stream per user with `job.progress`, `content.ready`, `grade.ready` and `attempt.voided` events. Event ids are \<process id>-\<sequence>; a reconnect with Last-Event-ID gets missed events replayed from a short per-user buffer, or one resync event when they cannot be replayed, and the client then refetches every resource it still shows as pending. While the stream is down, the client polls pending resources.

### 9.2 Resources

| Area | Endpoints |
| --- | --- |
| Auth | `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `POST /auth/password-reset`, `POST /auth/password-reset/confirm`, `GET /auth/oidc/google/start`, `GET /auth/oidc/google/callback` |
| Account | `GET /me`, `DELETE /me` (deletes everything), `GET /me/export` |
| Intake | `POST /uploads` (returns a signed upload URL), `POST /contents` (YouTube URL or upload id), `GET /contents`, `GET /contents/{id}`, `DELETE /contents/{id}` |
| Media | `GET /media/{media_object_id}` for playback, GET /cards/{id}/audio for a card snippet, GET /shadow/rounds/{id}/recording for the learner's own recording. Each checks ownership, then redirects to a short-lived signed URL |
| Sessions | `POST /sessions` (content, passage, entry), `GET /sessions/{id}`, `PATCH /sessions/{id}/entry` (refused once Transcript starts), `POST /sessions/{id}/steps/{step}/skip` |
| Blind | `POST /sessions/{id}/blind/attempts`, `POST /blind/attempts/{id}/heartbeat`, `POST /blind/attempts/{id}/gist` |
| Dictation | `POST /sessions/{id}/dictation/attempts`, `PUT /dictation/attempts/{id}/draft`, `POST /dictation/attempts/{id}/submit`, `POST /dictation/attempts/{id}/disputes` |
| Transcript step | `GET /sessions/{id}/transcript` (only from the Transcript step on), `GET`, `POST`, `PATCH`, `DELETE /sessions/{id}/marks` |
| Cards | `POST /sessions/{id}/cards`, `GET /cards`, `DELETE /cards/{id}` |
| Shadow | `PUT /sessions/{id}/shadow/segment`, `POST /sessions/{id}/shadow/rounds` (returns a signed upload URL), `POST /shadow/rounds/{id}/complete`, `GET /sessions/{id}/shadow/comparison` |
| Grades | `GET /gists/{attempt_id}/grade`, `GET /shadow/rounds/{id}/grade`, `POST /grades/{id}/retry` |
| Library | `GET /library/contents`, `GET /library/trends` |
| Admin | `GET /admin/usage`, `GET /admin/jobs`, `POST /admin/takedowns` |

Every session-scoped endpoint checks two things before anything else: the session belongs to the caller, and the session's current step allows the action. A refused action returns `409` with code `step_locked` and the open step.

## 10. Repository structure

One monorepo holds the web client, the backend, the AI evaluation sets, infrastructure and docs, so a feature that touches the API and the UI lands in one commit.

```
listenup/
├── apps/
│   ├── web/                    React + Vite client
│   │   └── src/
│   │       ├── app/            routes, layout, providers
│   │       ├── features/       intake, session, blind, dictation, review,
│   │       │                   cards, shadow, library, auth
│   │       ├── media/          player with per-mode control policies,
│   │       │                   recorder, waveform
│   │       ├── components/     shared UI
│   │       └── api/            client generated from OpenAPI
│   └── api/                    FastAPI app and workers (one Python package)
│       ├── src/listenup/
│       │   ├── main.py         API entry point
│       │   ├── worker.py       worker entry point (lanes: speech-interactive, intake, ai, background)
│       │   ├── platform/       config, db, storage, queue, events, security
│       │   ├── modules/
│       │   │   ├── identity/   content/   transcript/   practice/
│       │   │   ├── blind/      dictation/ review/       cards/
│       │   │   ├── shadow/     grading/   library/      notifications/
│       │   │   └── admin/
│       │   │       (each: api.py, service.py, domain/, repository.py,
│       │   │        models.py, schemas.py, jobs.py)
│       │   └── ai/
│       │       ├── ports.py    gateway.py   registry.py   quotas.py
│       │       ├── providers/  one file per provider adapter
│       │       └── prompts/    <task>/<version>.md + schema.json
│       ├── migrations/         Alembic
│       └── tests/              unit/, integration/, contract/
├── ai-evals/                   golden sets and the evaluation runner
├── infra/
│   ├── docker/                 Dockerfiles: api, worker, worker-media
│   └── compose/                compose.yml (local), compose.prod.yml
├── docs/
│   ├── architecture.md         this document
│   └── adr/                    one file per decision
├── .github/workflows/          ci.yml
└── CLAUDE.md
```

- The web client's mode rules (which controls exist in Blind, Dictation, Shadow) live in one place, `media/`, as **control policies** per mode, mirroring the server rules.
- The web shell (ADR 0018) keeps every route in one table in `src/App.tsx`: `/sign-in`, `/register`, `/forgot-password`, `/reset-password`, `/library` and `/sessions/:sessionId`. Pathless guard routes, `RequireAuth` and `RedirectIfSignedIn`, handle sign-in, and a same-site `next` parameter returns the learner after it. Every page except sign-in and register is a lazy chunk, and `pnpm size` fails CI when the initial JavaScript is over 200 KB gzip. Design tokens are Tailwind theme variables in `src/index.css`, named after the design system's tokens and redefined for the dark theme.
- The `media` worker image, which serves the `speech-interactive` and `intake` lanes, carries ffmpeg, yt-dlp and the speech models; the `default` worker (`ai` and `background` lanes) and the API image stay small.
- Local development runs `docker compose up` for PostgreSQL, SeaweedFS (S3 gateway on port 9000, with a one-off service that creates the listenup bucket), Mailpit (email catcher), the API and both workers, plus the Vite dev server.

## 11. Deployment

Production runs on one free virtual machine with Docker Compose, plus free managed PostgreSQL, object storage and a CDN; because every piece is a container or a standard API, moving to paid hosting is a configuration change.

&#91;embedded content: production deployment · one VM, three managed free services\]

| Environment | Where | Purpose |
| --- | --- | --- |
| Local | Docker Compose: PostgreSQL, SeaweedFS, Mailpit, API, both workers; Vite dev server | Development and integration tests |
| CI | GitHub Actions with service containers | Lint, type checks, tests, image builds |
| Production | Free VM running Compose behind Caddy; managed PostgreSQL; S3-compatible storage; CDN for the web app | Learners |

**Choosing the free VM.** The media worker needs several CPU cores and several gigabytes of memory for the speech models, which rules out most free container platforms that sleep or cap memory. An always-free Arm virtual machine from a major cloud (for example Oracle Cloud's Always Free tier) is the best fit at the time of writing; check current limits before committing.

**Deploys.** A push to `main` that passes CI builds versioned images, pushes them to the registry, and the VM pulls and restarts with `docker compose up -d`. Database migrations run as a one-off container before the API restarts.

**Backups.** The managed PostgreSQL tier's backups, plus a nightly `pg_dump` to object storage, kept for 14 days. Media is not backed up separately; it can be re-derived or re-uploaded.

**When to move.** Move the media worker to a bigger or GPU machine when the median grading wait exceeds a target (to set), and the database to a paid tier when free storage reaches 80%.

## 12. Security, privacy, observability and testing

The largest risks are learner voice data, untrusted uploads and untrusted text sent to AI, so each has a specific control rather than a general policy.

### 12.1 Security

| Threat | Control |
| --- | --- |
| Reading another learner's data | Every query is scoped by `user_id` from the session; an integration test calls every endpoint as a second user and expects 404 |
| Leaked media links | Private bucket; signed URLs expire in minutes; Blind URLs are bound to one attempt |
| Malicious uploads | Size limit before upload, ffprobe validation, ffmpeg re-encoding in a sandboxed worker container with no network access to internal services |
| yt-dlp or ffmpeg exploits | Media worker runs as a non-root user with a read-only filesystem except its scratch directory, and with CPU, memory and time limits per job |
| Prompt injection in gists | Delimited data blocks, fixed output schema, range checks, scores computed by our code |
| Credential attacks | Argon2id hashes, login rate limits, account sign-in lock for 15 minutes after 5 failed attempts, session rotation on login, secure cookies, CSRF tokens |
| Secrets exposure | Secrets only in environment variables or the host's secret store; never in the repo or logs |
| Dependency vulnerabilities | Automated dependency updates and vulnerability scanning in CI |

### 12.2 Privacy

- **Consent:** recording consent is stored with its version before the first Shadow round.
- **Minimum data to AI:** providers receive audio or text only, never email or user ids; ineligible providers are skipped by the gateway.
- **Deletion:** deleting content, a session or the account removes database rows (cascade) and storage objects (by prefix) in one job, with a report of what was removed. An account is first disabled for a 7-day grace period in which signing in restores it; the deletion job runs when the period ends.
- **Retention:** recordings kept for 90 days, then deleted by a scheduled job; grades and word labels stay.
- **Export:** a learner can download their data as JSON plus their media files; YouTube media is excluded.

### 12.3 Observability

- Structured JSON logs with a request id that follows a request into the jobs it creates.
- OpenTelemetry traces across API, queue and workers; metrics for job wait time, job duration, failure rate, AI latency and remaining free quota per provider.
- Alerts on: job backlog growing, a provider quota under 20%, grading failure rate over 5%, error rate spikes.
- Errors go to an error tracker through its open SDK, swappable like any other adapter.

### 12.4 Testing

| Level | What | Tools |
| --- | --- | --- |
| Unit | Domain rules: session state machine, Blind integrity checks, Dictation diff, card limit, score weighting, repeated-mistake detection | pytest, Hypothesis (property tests for the diff) |
| Integration | API plus database plus storage, ownership checks, job handlers | pytest with PostgreSQL and SeaweedFS containers |
| Contract | Every AI provider adapter returns the port's schema; recorded responses replayed in CI | pytest |
| AI quality | Golden-set agreement and consistency (section 7.4) | `ai-evals` runner |
| End to end | The three plan paths, Blind lock (pause, seek, reload, leave), card limit, Shadow recording with a fake microphone; a smoke test of the web shell (a signed-out learner opens a session, signs in and lands back on it) | Playwright with Chromium's fake media stream |
| Front end | Player control policies, forms, error states | Vitest, Testing Library |

CI on every push: lint, type checks, unit and integration tests, contract tests, import-linter boundaries, and the AI smoke set when prompts or providers change.

## 13. Decisions, risks and build order

The design rests on eleven decisions (0001 to 0011), and the build has added more from 0012 on, each written up as an ADR in `docs/adr/`; the build starts with the riskiest technical pieces so a wrong assumption surfaces in the first weeks.

### 13.1 Architecture decisions

| ADR | Decision | Main reason | Revisit when |
| --- | --- | --- | --- |
| 0001 | Modular monolith, not microservices | One small team, one deploy; boundaries kept by import rules | A module needs independent scaling or ownership |
| 0002 | Python for API and workers | Speech and media tooling is Python; one backend language | Never likely |
| 0003 | React single-page app, not server-rendered | Logged-in, media-heavy app; static hosting is free | Public, search-indexed pages are needed |
| 0004 | PostgreSQL-backed job queue | No Redis to run or pay for; jobs commit with data | Job volume exceeds what the database handles comfortably |
| 0005 | S3-compatible storage with signed URLs | Standard API, portable, no public bucket | Never likely |
| 0006 | Own authentication with Google sign-in, no hosted auth | No per-user fees, no lock-in | Enterprise sign-in or compliance needs appear |
| 0007 | Server-enforced Blind integrity via heartbeats | Client-only locks are trivially bypassed | Abuse patterns show the checks are too strict or too loose |
| 0008 | Deterministic Dictation scoring | Explainable, free, testable | Never likely |
| 0009 | AI behind ports and a gateway with config-driven providers | No vendor lock-in; free tiers can be swapped | A paid provider is adopted (configuration only) |
| 0010 | Self-hosted speech pipeline as the default for recordings | Free and keeps voice data on our servers | Accuracy on the golden set is not good enough |
| 0011 | Server-side YouTube download, isolated in the media worker and behind a feature flag | Full playback control (pending legal review, OQ-6) | Legal review advises against it |
| 0012 | SeaweedFS for local S3 storage | MinIO images are no longer published on Docker Hub; the app uses only the S3 API | SeaweedFS stops serving the S3 calls the app uses |
| 0013 | Hand-written SQL migrations with row-level security from the first table | Constraints, triggers and policies that autogenerate cannot express; a missing learner setting fails closed | Never likely |
| 0014 | One transaction per request, committed before the response | A client never sees a success the database did not keep | Never likely |
| 0015 | Job lanes on Procrastinate, with a vendored schema | Lanes, retries, transactional enqueue and backpressure without new infrastructure | Procrastinate is upgraded (apply its migration files) or job volume outgrows PostgreSQL |
| 0016 | Live events over Server-Sent Events, fed by PostgreSQL NOTIFY | Ids-only events; resync plus refetch keeps several API processes correct | Stage 2: Redis publish and subscribe behind the same hub |
| 0017 | Password reset tokens minted by the email job | Raw tokens never sit in job arguments, logs or tables | Never likely |
| 0018 | Web shell with declarative routes, lazy pages and design tokens in Tailwind | Server data stays in TanStack Query; initial JavaScript under 200 KB | Loaders or route-level prefetching become worth having |
| 0019 | Dictation scoring rules: spelling slips count as correct, slip limit scales with word length | The product scores listening, not spelling; one constant flips the rule | Near words need telling apart, for example with a dictionary |

### 13.2 Technical risks

| Risk | Effect | Mitigation |
| --- | --- | --- |
| Accent and articulation scores are unreliable on CPU-friendly models | Wrong feedback damages trust | Ship accent as "experimental", calibrate on the teacher set, test across speaker accents before launch |
| Whisper-style models drop filler words | Filler counts too low | Benchmark filler recall on the golden set; use a disfluency-aware transcription setting or model; label the count as an estimate until it passes |
| CPU speech jobs too slow on a free server | Feedback arrives minutes late | Benchmark early (milestone 1); queue with progress events; limit passage and segment length (already 15 minutes and 90 seconds) |
| YouTube changes break yt-dlp | Intake fails for links | Keep yt-dlp updated automatically; upload fallback; isolated downloader |
| Free tiers shrink or change terms | A role loses its provider | Self-hosted default for every role; gateway fallback; quota alerts |
| Free hosting limits (memory, disk, sleeping instances) | Outages | Containers run anywhere; documented move to a paid VM costs a configuration change |

### 13.3 Build order

1. **Technical spikes (riskiest first):** YouTube download and conversion; transcription with word times on CPU; forced alignment; a first speech-measure prototype on 10 recordings; CPU timing benchmarks.
2. **Foundations:** monorepo, CI, Docker Compose, platform package, auth, database migrations, storage, job queue, event stream.
3. **Intake and transcripts:** upload intake first, then YouTube intake behind a feature flag (off until the legal review clears it), media conversion, caption import, transcription, library list.
4. **Practice core:** session state machine, plan paths, Dictation with deterministic scoring, Transcript step with marks.
5. **Blind:** locked player, heartbeats and integrity checks, gist submission, AI gateway, key points and gist grading.
6. **Cards:** two-card limit, snippet cutting, card review.
7. **Shadow:** segment picker, recording, speech assessment pipeline, per-round feedback, three-round comparison.
8. **Hardening:** golden-set evaluation, fairness checks, security tests, privacy flows (export, deletion, retention), observability and alerts.
9. **Launch:** production deploy on free tiers, upload-only unless the legal review has cleared the YouTube flag (OQ-6), beta with a small group of learners.
