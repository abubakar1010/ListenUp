# ADR 0061: Private card audio and durable cleanup

- Status: Accepted
- Date: 2026-10-25

## Context

FR-CA-2 requires audio around the marked phrase. System Design §§4.1 and 6.1
specify intake-lane AAC snippets lasting 3 to 6 seconds, retained until card
deletion. Source playback may expire independently. Marks may contain up to
20 words, which can exceed six seconds. The owner approved this plan, including
refusing card creation for a phrase longer than six seconds.

## Decision

- Snapshot absolute, half-open snippet bounds at card creation through the
  authorized transcript service. Include the complete phrase with up to one
  second of balanced context; expand short phrases to three seconds and clamp
  the window to the source. Refuse phrases longer than six seconds with
  `card_phrase_too_long`, without consuming a slot.
- Queue generation transactionally on the existing intake lane. Encode AAC-LC,
  mono, 64 kbit/s in faststart MP4 (`snippet.m4a`) in sandboxed scratch space.
  Store one deterministic key under `users/<learner>/cards/<card>/`.
- Add `audio_status` (`unavailable`, `pending`, `ready`, `failed`). Existing cards
  remain unavailable; no backfill or card review is introduced. Keep existing
  `snippet_key` and `snippet_span`; enforce finite 3–6 second spans and require
  both values for ready audio.
- Retry transient failures using the intake lane's five-attempt backoff. Final
  failure publishes the failed state. An ownership-checked, CSRF-protected retry
  endpoint allows another attempt; missing/expired source media is permanent.
- Recheck and lock the card immediately before uploading and publishing readiness.
  Deletion during encoding prevents upload; deletion during upload waits for
  commit. Repeated deliveries for ready/deleted cards do nothing.
- `GET /cards/{id}/audio` checks ownership and readiness before a private,
  non-cacheable 307 redirect, signed for at most 120 seconds. It reads the snippet
  independently of the source media and mark. Storage keys/URLs never appear in
  card JSON.
- A deletion trigger records a deterministic cleanup tombstone, including session
  cascades. A background job deletes storage before removing the tombstone;
  failures retain it. Explicit card deletion queues cleanup immediately, and a
  minute sweep recovers cascades and exhausted jobs. Account purge already sweeps
  the learner prefix before and after its database cascade.
- Cards-local controls support keyboard playback, preparation/failure states and
  retry. Events invalidate the session's cards; pending lists poll each second.
  Unmount pauses playback. Shared-player and design-system code stay untouched.
- Data exports omit internal snippet keys, include uploaded-source snippets, and
  exclude YouTube-derived files. Cleanup metadata follows learner ownership.

## Consequences

Cleanup is asynchronous and survives storage outages; already signed URLs can
remain usable until their short lifetime ends or object deletion completes.
Card creation needs authorized word timings. Queue contention/backpressure can
exceed the usual few-second readiness target; local functional evidence is not
staging performance evidence. YouTube intake remains disabled; expiry tests use
synthetic media metadata and remove actual source bytes without downloading.
