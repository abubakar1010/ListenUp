# Reconcile an unresolved card snippet writer

ADR 0064 uses `practice.card_snippet_writes` to preserve deletion responsibility
when a media worker loses its DB connection, is killed, or cannot confirm an S3
upload. Card cleanup skips these writers. Account purge postpones before its first
storage sweep; the user FK also refuses deletion while a registration exists.

Do not delete a registration based on age, a heartbeat, queue status, a missing
object, or a successful newer retry. None proves that an earlier storage request
cannot complete later. A normal settled writer removes its own registration using
a fresh DB transaction, even if result persistence failed.

Inspect as the database owner or worker role:

```sql
SELECT id, card_id, user_id, owner, created_at
FROM practice.card_snippet_writes ORDER BY created_at;
```

For each unresolved registration:

1. Identify the exact host/process in `owner` and its generation job. Stop that
   writer and prevent its replacement from starting while reconciling. Stop the
   media pool if the original process cannot be identified conclusively.
2. Establish with the storage service that the outstanding write has finished or
   has been cancelled and cannot complete later. A client-side timeout or killing
   its process alone is insufficient. If this cannot be established, retain the
   registration and leave cleanup/purge pending.
3. Once the writer and remote request are conclusively settled, remove only that
   registration by its exact `id` in a transaction. Do not clear the whole registry.
4. Resume media workers. The minute Cards sweep deletes tombstoned snippets;
   account purge retries after its minute postponement. If the card still exists,
   its pending job may be redelivered, or its failed audio retried through the
   authenticated Cards UI. Verify cleanup/purge completion and object absence for
   a deleted card/account.

For example, after steps 1–2 have been completed and documented, use a bound UUID
parameter for `DELETE FROM practice.card_snippet_writes WHERE id = :writer_id`.
Never expose owner/process metadata in API responses or learner exports.

Stop media workers before applying `73_audio_lifecycle` so old code cannot upload
without a registration. Legacy queued jobs have a NULL generation identity and
remain compatible. Downgrade also requires stopped workers and an empty registry;
the migration refuses to discard unresolved registrations. Apply upgrades normally
before restarting updated workers. This registry is specific to Cards; unmerged
PR #142's general storage-writer implementation is not a prerequisite.
