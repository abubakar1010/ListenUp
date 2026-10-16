# ADR 0038: Passage transcription cache and authorized reads

- Status: Accepted for implementation; stage-0 latency validation outstanding
- Date: 2026-10-16
- Implements: #45; FR-TX-1, FR-TX-3, FR-TX-5, NFR-AI-5
- Sources: Database Design 4 and 9.2; System Design 3, 5.1 and 8.1; ADRs 0028, 0034

## Decision

Starting a plan is the persisted passage-selection boundary. It queues
`transcript.transcribe_passage` on the intake lane in the request transaction.
The unique key is per session, so every learner receives readiness for their own
session, including on a cache hit. The queue resource lock is per media object.

The worker pads the selection by five seconds on each side, bounded by duration,
and subtracts ready cached ranges. It downloads the playback file to temporary
scratch space, extracts only missing windows with ffmpeg, and invokes the configured
transcription gateway. The existing adapter applies VAD and preserves time offsets
through silence. No model, provider, or AI policy changes are made by this story.

Migration 0017 creates the designed `content.passage_transcripts` table, with finite,
nonempty half-open millisecond spans and the GiST exclusion constraint for non-failed
rows. Words have absolute media timestamps, confidence scaled to 0–1000, and sentence
start indices derived from sentence-ending punctuation across provider segments;
acoustic chunk boundaries do not by themselves start a new sentence. Common
person titles (Dr., Mr., Mrs., Ms., Prof. and Rev.) do not end a sentence. Each ready
row retains the actual provider, model, version and `generated` origin. Empty output is valid coverage of
silence. Empty, invalid or unordered word timings are rejected rather than stored.
The cache enforces non-null confidence values in 0–1000, valid non-null sentence
indexes and a provenance object with nonempty provider/model/version strings on
ready rows. Pending/failed markers may retain empty provenance.

A PostgreSQL session advisory lock additionally serializes direct invocations and
failure settlement. It is held on a dedicated checked-out connection across short
transactions, with no idle transaction during inference. Contention reschedules
without consuming the failure budget. Unlock failure invalidates the connection;
process death releases the lock. The exclusion constraint remains the last defense
against writers outside this protocol.

Each completed gap commits independently. A retry recomputes uncovered ranges and
preserves completed work. Exhausted failures mark only missing spans failed; failed
rows never count as cache coverage or block later writes. Reads consult failure
markers only for currently missing ranges. Scratch files are removed on success,
exception and cancellation; ffmpeg is terminated when its task is cancelled.

The service's `read_passage` accepts an RLS request session and an explicitly supplied
worker-role database. It checks session ownership, `require_reached(TRANSCRIPT)` and
content access before opening the privileged cache read. Neither the API nor the
reporting role receives table privileges. It concatenates words in time order,
selects words starting inside the chosen passage, bounds final word ends, rebases
sentence indices without treating a cache-span boundary as a new sentence, and retains provenance of the contributing spans. No HTTP
transcript route or Transcript screen is introduced by #45.

`transcript.ready` carries the session ID only and is published after the cached
results commit. PostgreSQL delivers the notification when the notification transaction
commits. Retrying a notification failure reuses the cache. `transcript.failed` is
published with committed failure markers. Notifications can repeat on retries, as
invalidation signals; they carry no transcript text or storage key. The browser
subscribes to both named events so its event callbacks receive readiness and failure
changes. SSE documentation and the generated API client list both events.

## Consequences and validation limits

Uploaded media retains the existing learner-scoped fingerprint: identical uploads
from different learners do not share transcripts. Authorized learners of the same
shared media may reuse cached spans. Jobs stop for removed sessions or inactive
accounts and recheck access after inference.

This implements the transcript service boundary; a later Transcript route must wire
its privileged database connection and use this service rather than querying the
cache itself. Caption import, corrections, reference profiles and grading remain
separate stories.

The stage-0 host is not documented or configured in this environment (#16, #112).
No p95 claim is made. The real S3/ffmpeg test uses configured fake AI and proves
plumbing only; existing adapter contracts prove mapping, not stage-0 performance.
