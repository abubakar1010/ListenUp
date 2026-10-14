# Unfinished storage writers

Conversion and export commit an `ops.storage_writes` registration before uploading
(DR-1, ADR 0029). They retain it until every upload finishes, including after job
cancellation, direct cancellation of retained upload tasks during shutdown, or
loss of the database connection. S3 writers retain executor futures directly so
shutdown cancellation cannot abandon the synchronous upload thread. Purge refuses to sweep while a
registration remains. The foreign key also prevents deletion of the account row.
Normal success removes the registration with the result commit. Cancellation
and database failure remove it in a separate transaction after uploads have
confirmed completion. An S3 upload error raises `StorageWriteUncertain` and keeps
the registration, including when that error occurs during cancellation draining;
the client error cannot prove the server has stopped writing.

Deploy migration 0015 with workers stopped and their uploads settled before
restarting updated workers. Old workers do not register writes. Downgrade also
requires stopped workers; the migration refuses to drop a nonempty registry.

A killed worker, uncertain S3 upload or failed cleanup connection can leave a registration. Purge
retries normally, then its due-request sweep requeues it after the existing retry
interval. This is a deletion blocker that operators must reconcile; it never
expires by age or worker heartbeat, because neither proves an S3 write has stopped.

Inspect registrations as the database owner:

```sql
SELECT id, subject_user_id, owner, created_at
FROM ops.storage_writes ORDER BY created_at;
```

`owner` identifies the container/host and process ID. Confirm whether that exact
worker is still running, using its creation time to avoid confusing a reused PID.
Let a live worker settle its upload. If it must be stopped, stop that process and
verify all of its storage requests have completed or been reliably aborted at the
S3 server. Check server request/transfer evidence; killing the client, a stale
heartbeat, an old registration, or aborting only an incomplete multipart upload
does not establish that an already submitted completion or PUT cannot still finish.
When completion cannot be established, keep the registration and escalate the
storage investigation; do not report the account as purged.

Only after every write from that owner is settled, remove the specific reconciled
registration as the database owner, using its exact UUID:

```sql
DELETE FROM ops.storage_writes WHERE id = '<reconciled registration UUID>';
```

Retry the account's purge through the existing job queue, or let the scheduled
sweep retry it. Confirm the deletion request reaches `completed` and its prefix
is empty. Record the storage evidence and reconciliation in the operations log.
The API role has no access to this registry; it contains operational ownership,
not learner export data.
