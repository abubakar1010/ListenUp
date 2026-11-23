# ADR 0098: Takedowns of uploaded files by their hash, keeping the learners' practice

- Status: Accepted
- Date: 2026-11-01
- Sources: #105 (non-YouTube half; the YouTube half waits for #38); SRS 2.2 (Administrator), OI-1 (OQ-6 mitigation), NFR-USE-3; [Software Architecture 4.1 (`admin`: takedown records) and 9.2 (`POST /admin/takedowns`)](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13); [Database Design 7 (`ops.takedowns`)](../design/database-design.md); ADRs 0013, 0020, 0022, 0045, 0085

## Context

A rights holder may ask us to remove content. An administrator records the takedown; the media must then go for every learner who has it, those learners must be told in plain words what happened and why, and the same source must not come back. The design names the route and an `ops.takedowns` table with a `fingerprint` "kept so the same source can be refused later" and one `media_object_id`.

Three facts shape the upload half:

- **An upload's fingerprint is per learner** (`upload:<user id>:<sha256>`, ADR 0020), so two learners who upload the same file have two media objects. Matching the stored fingerprint exactly would remove one learner's copy and miss the rest, and would not refuse the next learner.
- **The hash is known only to the conversion job** (ADR 0020, 0022). The API never sees the bytes, so intake cannot refuse before the upload; it can refuse when the job hashes the file.
- **The learner's practice hangs off the media object.** Sessions reference the content item, which references the media object (`ON DELETE NO ACTION`). The issue keeps sessions and marks (their data) and shows the media as unavailable. Deleting the media object would delete all of it.

## Decision

- **A takedown names the source without a learner id: `upload:<sha256>`**, the lower-case hex SHA-256 of the file the rights holder identified (an administrator computes it with `sha256sum`). `ops.takedowns.fingerprint` is unique and checked against that form; #38 widens the check for `youtube:<video id>`. A second takedown of the same file answers 409 `takedown_exists` with the first one's id. The administrator's `reason` (at most 2,000 characters) is internal and never reaches a learner. A fixed `grounds` (`copyright`, `other_rights`, `unlawful`) chooses the sentence learners read (`content/domain/takedown.py`). The design's single `media_object_id` is replaced by the reverse link `content.media_objects.takedown_id`, since one upload takedown removes many media objects.
- **The media object stays, with status `removed`.** A check ties `removed` to a non-null `takedown_id`. Its playback, peaks and video keys are cleared, and its files (`users/<id>/media/<media id>/`, any original under `uploads/`) are deleted. Content items, sessions, marks, cards, transcripts, corrections and the learner's own Shadow recordings stay. Card snippets are cut from the clip, so they are deleted too: the cards keep their phrase and reviews with `audio_status = 'unavailable'`.
- **`POST /admin/takedowns`** (admin only through `CurrentAdmin`, ADR 0045; `Idempotency-Key` through `run_once`) inserts the row and queues `admin.apply_takedown` in one transaction, then answers 202 with the id, fingerprint, grounds, `received_at` and `actioned_at` (null until done). Like every admin answer it carries no learner data and is `private, no-store`.
- **The job follows content deletion's order (ADR 0085)**, running as `listenup_worker` because it acts for many learners:
  1. One transaction is the barrier. Every upload whose fingerprint ends in the hash becomes `removed`, and every card cut from those media becomes `unavailable`. Each owner gets `content.ready` (and `card.audio_updated`). It commits before any other step, so from then on nothing plays: `GET /media/{id}` and `/peaks` answer 410 `media_removed`, starting a plan answers 409 `content_not_ready`, card audio answers 409, and transcription, profiling and snippet jobs find no playable source.
  2. A second transaction waits (`Reschedule`) while a conversion (`content.media_writes`) or snippet writer (`practice.card_snippet_writes`) of those media is registered. A registration is never presumed dead.
  3. Storage deletes run outside any transaction.
  4. The record gets `actioned_at` and a report with counts only (`media_removed`, `learners`, `objects_removed`). A repeated run deletes again harmlessly and reports the same. `admin.reconcile_takedowns` re-queues unactioned takedowns every 10 minutes.
- **Intake refuses the file.** `content.convert_upload` checks `ops.takedowns` when it hashes the file, before the duplicate check (otherwise the learner's removed copy would absorb the new item as a duplicate). It checks again in the transaction that would make the clip playable, which catches a takedown that commits after hashing but before the barrier scanned this media object. A refused item is `failed` with `error_code = 'source_taken_down'` and a plain sentence; its original and any written playback files are deleted.
- **Learners are told in-app.** The content page shows "This clip was removed" with the grounds' sentence (for example, "We removed this clip because its copyright owner asked us to. It can't be played or added to ListenUp again. Your sessions, marks and cards are kept.") and links to their marks and cards. `GET /contents/{id}` returns it as `removal: {grounds, message}`. The library shows a "Removed" badge. A learner online at the time also gets a live notice ("“title” was removed from ListenUp after a rights complaint.") through the existing `content.ready` path.
- **Ownership of the table.** The admin module writes `ops.takedowns` and runs the job; the content module owns media state, so it reads the table for intake and for the learner's `grounds`, and holds the vocabulary and sentences. `ops.takedowns` has no `user_id` and no learner data, so it has no row-level security; `listenup_api` gets SELECT and INSERT, the worker SELECT, INSERT and UPDATE, `listenup_readonly` nothing (the reason may name the rights holder).

## Consequences

- Migration `105_takedowns` adds the table, `media_objects.takedown_id` and the `removed` status. Its downgrade refuses while any takedown exists, since dropping the records would let a taken-down file back in.
- The block is exact: a re-encoded or trimmed copy has another hash and is not refused. Automated content ID is out of scope (#105).
- A conversion that started before the barrier and crashes after its upload but before it settles leaves its registration and possibly an object, as in content deletion: the operator reconciles it ([content-deletion runbook](../runbooks/content-deletion.md)). A conversion that finishes normally finds its media `removed` and deletes its own files.
- Transcripts, reference profiles and key points of a removed upload stay, because the learner's marks and cards are anchored in that text. Whether transcript text of taken-down content must also go is a question for the legal review (#102); removing it would need a separate decision about marks.
- Exports keep the removed clip's rows but no media file or original.
- The learner's reply to a mistaken removal, and closing accounts that break the terms, are #181. The terms still need a published takedown contact; see the pull request for proposed wording. The consent version is unchanged.
- The YouTube half (#38) adds the `youtube:` fingerprint, removal of the shared playback file, and the refusal at URL intake, which can check before downloading.
