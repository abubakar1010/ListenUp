# ADR 0085: Content deletion and durable conversion writers

- Status: Accepted (owner-approved plan and narrow writer-fence scope)
- Date: 2026-10-28
- Sources: #89; FR-CI-7, DR-2, FR-SH-17, NFR-SEC-5; ADRs 0013, 0029, 0035, 0064

## Decision

Content deletion is confirmed, learner-scoped, and asynchronous. Mark the content
as deleting before cleanup so new work cannot issue storage writes. Keep a durable
`ops.deletion_requests` manifest of the exact private prefixes and object keys.
Remove storage before deleting rows. Retry missing objects without error; retain
failed requests for recovery. Never sweep the entire learner prefix for a content
deletion. Analytics events survive, as required by ADR 0035.

Conversions register a durable `content.media_writes` row before writing playback
or peaks, under the same content-row lock as deletion. Deletion waits for these
registrations and existing card-snippet registrations. Uncertain storage results
retain the registration for operator reconciliation rather than guessing from age
or job state. The owner explicitly authorized this conversion-only part of #228;
export fencing and the other #228 work remain outside this story.

Shared YouTube media and its caches remain while another content references it.
When the last reference disappears, the reference-count trigger makes it eligible
for the seven-day orphan sweep. The owner approved splitting #89's third criterion:
#89 proves orphan eligibility; #93 implements and tests timed removal. Upload media
and its shared caches are removed with the uploader's content.

Signed browser uploads can outlive a request. Cleanup retains its durable manifest
and reconciles late objects; completion must not erase the only record of a key.
Writer registrations must never be expired automatically. The implementation and
validation record document the remaining operator and signed-upload boundaries.

Stored idempotency responses can also contain submitted text. Delete only the
selected learner's responses with structured references to the content, media,
sessions, attempts or cards. Arbitrary learner text containing a UUID is not a
reference. Acquire existing key locks before parent deletion, matching `run_once`'s
key-before-session order, and repeat after cascades to cover in-flight commits.
Unrelated keys and every other learner's cache remain untouched. Retries of a
removed response must pass the ordinary parent lookup, which refuses deleted data.
