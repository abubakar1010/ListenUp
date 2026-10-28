# Content deletion and conversion-writer reconciliation

Content deletion (#89, ADR 0085) marks the selected clip before returning 202.
The API saves its private storage manifest in `ops.deletion_requests` in the same
transaction as the marker and background job. A marker prevents new conversions,
plans and snippet writes. The worker drains registered writers, removes objects,
then cascades rows and completes the audit. Related idempotency responses are
removed by structured resource references before and after the cascades so saved
submission text cannot outlive the clip. Existing key locks precede parent locks;
unrelated requests and other learners are untouched. Analytics events remain under DR-2.

## Deploy the migration

Before applying `20261028_89_content_deletion.py`, stop both worker pools and
settle outstanding conversion uploads. Old workers do not register their writes;
they must not overlap the new deletion worker. Apply the migration, deploy the
updated API and workers together, and restart the pools. Do not enable the delete
endpoint while old media workers can still upload. The migration is hand-written
SQL and includes explicit API grants and learner RLS for `content.media_writes`.

Downgrade requires stopped workers, no pending content deletions, and an empty
conversion registry. Also establish that previously signed browser uploads cannot
finish later before disabling the new cleanup worker; otherwise retain the current
version and its reconciliation schedule. The migration refuses to discard unresolved writers. Reconcile
writers and finish content deletions before rolling back application code.

## Unresolved conversion writes

Inspect using the owner or worker role:

```sql
SELECT id, media_object_id, user_id, owner, created_at
FROM content.media_writes ORDER BY created_at;
```

Never delete a registration based on its age, queue status, heartbeat, a newer
successful retry, or an absent object. A missing response does not prove a storage
request cannot finish later. Direct child-task cancellation during shutdown also
retains the registration: the executor or remote request may outlive that task.

1. Identify the exact host/process in `owner`, stop that writer and prevent a
   replacement from uploading. Stop the media pool if identity is uncertain.
2. Establish with the storage service that every outstanding PUT/multipart upload
   is finished or cancelled and cannot complete later. Killing the worker alone
   is insufficient. If this cannot be established, retain the registration.
3. After documenting that evidence, delete only the reconciled registration by a
   bound `id` in a transaction. Do not clear the registry wholesale.
4. Restart the media pool. Deferred deletion jobs retry after one minute. Verify
   the request completes and all prefixes/keys in its manifest are absent.

Card writers use their existing [reconciliation runbook](card-snippet-writers.md).
The conversion guard is also registered with account purge, so an uncertain
conversion blocks its first storage sweep. Export fencing and the other #228
items remain separate work.

## Retries and late browser uploads

The minute `library.reconcile_content_deletions` schedule queues due manifests,
including exhausted failures, using the same unique key and execution lock as the
initial job. Each processed manifest rotates its next recovery check one hour
forward so a batch of 1,000 does not permanently starve later requests.

Completed manifests are deliberately retained and reconciled too. A browser PUT
signed before deletion can arrive later; the retained exact upload key and private
session prefixes keep that object referenced and removable after the parent rows
have gone. This is eventual late-write cleanup, with an hourly recheck after the
initial cleanup; it does not revoke an already issued S3 URL. Deleted content no
longer authorizes new upload URLs. Never remove a manifest as an optimization
without a replacement that proves all remote writes and signed URLs are settled.

`objects_removed` counts objects confirmed removed by completed prefix calls;
a storage response lost after partial deletion can undercount. `sessions_removed`
records the request snapshot. Keys and prefixes are internal audit data, never
learner-facing URLs. There is no claim of an exact per-table row inventory.

## Shared media boundary

Deleting one learner's YouTube content preserves other learners' sessions,
corrections, objects and shared caches. The last reference reaches `ref_count=0`
with its updated orphan timestamp. #93 owns removal after seven days, including
transcripts, profiles and key points; #89 does not implement that sweep.
