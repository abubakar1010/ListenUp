# ADR 0020: Uploads are confirmed against a pending-upload table, and hashed by the conversion job

- Status: Accepted
- Date: 2026-10-03

## Context

Issue #35 sends uploaded files from the browser straight to object storage (Architecture 5.1 and 9.2): `POST /uploads` returns a signed URL, the browser PUTs the file with a progress bar and a cancel button, and `POST /contents` with the upload id confirms it. Three questions were left open:

- **What the server remembers between the two calls.** `POST /contents` must know which learner the upload belongs to, its storage key, and the size and type that were declared and checked.
- **How the 2 GB per-account cap (D5, FR-CI-3) is counted**, including uploads that are on their way.
- **How the fingerprint `upload:<user id>:<sha256>` (Database Design 4) is computed.** Its purpose is that the same file appears once in one learner's library, and is never shared with another learner. Hashing a 500 MB file in the browser means reading all of it into memory (Web Crypto has no streaming digest) before the upload can even start; the API never sees the bytes.

## Decision

- **A small table, `content.uploads` (migration 0006).** `POST /uploads` checks the declared name, MIME type and size, then inserts a row with the storage key `users/<user id>/uploads/<upload id>.<ext>`, the file name, the type and the size, under the `own_rows` policy. `POST /contents` locks the row, checks the object in storage and links the row to the new media object and content item. A signed, self-contained upload token would have avoided the table, but it would need a new application secret, could not be revoked or listed, and would leave nothing to count the storage cap from or to find abandoned objects with. The row is deleted with its content item (`ON DELETE CASCADE`) and with the account.
- **The signed URL is bound to the type and the exact size.** The signature covers `Content-Type` and `Content-Length`, so storage refuses any other body, and the signed URL lives for `signed_url_ttl_seconds` (an upload must start within it; a started upload may take as long as it needs). Confirmation still checks with a `HEAD` request that the object exists and has the declared size; a mismatch deletes the object and refuses with `upload_size_mismatch`.
- **Limits.** 500 MB per file (`LISTENUP_UPLOAD_MAX_BYTES`, binary megabytes as operating systems show them) is checked before any byte is sent. The 2 GB cap (`LISTENUP_UPLOAD_QUOTA_BYTES`) counts the declared size of every confirmed upload still in the library plus every unconfirmed upload that can still be confirmed (`LISTENUP_UPLOAD_CONFIRM_HOURS`, 24 h). A cancelled upload (`DELETE /uploads/{id}`) stops counting at once. A per-learner advisory lock makes two simultaneous requests count one after the other. Requests to `POST /uploads` are limited per learner (`LISTENUP_UPLOAD_RATE_LIMIT` per hour).
- **The hash is computed by the conversion job.** Confirmation creates the media object with a provisional fingerprint, `upload:<user id>:pending:<upload id>`, which is unique and still scoped to the learner. The conversion job (#36) reads the whole file anyway; it hashes it while streaming and sets `upload:<user id>:<sha256>`. If the learner already has a media object with that fingerprint, the new item is a duplicate within their library, and #36 decides how to merge it (for example, removing the new item and pointing the learner at the existing one). Deduplication therefore stays within one learner's library, as the design intends, and happens a few seconds later instead of before the upload.
- **Confirmation is idempotent.** `POST /contents` runs in `run_once` with the `Idempotency-Key` header, and confirming an already confirmed upload without a key returns the same item with `200` instead of `201`. It queues `content.convert_upload` on the intake lane in the same transaction, with a unique key per media object.

## Consequences

- Cancelling an upload leaves no content item; an abandoned upload leaves an unconfirmed row and possibly an object under `users/<id>/uploads/`. A background sweep should delete unconfirmed rows older than the confirm window, with their objects (`uploads_unconfirmed_idx`), and objects under that prefix that no row names. This sweep is follow-up work.
- The cap counts the uploaded file's size, not the smaller playback file kept after conversion. #36 may switch the count to `playback_bytes` once it stores it.
- Production storage needs a CORS rule that allows `PUT` from the web origin with the `Content-Type` header; the local SeaweedFS allows any origin.
- The daily limit of new audio minutes (D16) needs the file's duration, which only the conversion job knows; it belongs to #36 and the rejection-messages story #39.
