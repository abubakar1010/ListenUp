# Takedown requests (uploaded files)

Internal procedure for an administrator handling a notice that content on ListenUp
infringes someone's rights (SRS 2.2, #105, [ADR 0098](../adr/0098-upload-takedowns-by-file-hash.md)).
This covers uploaded files only; YouTube links follow with #38. The learner's reply
to a removal is #181 and is not built yet.

## 1. Receive and review the notice

1. Keep the notice as received (email and attachments) in the operator's records,
   outside the application. Never paste it into an issue or a pull request.
2. Check it is complete: what content is meant, the rights the sender holds, and
   their contact details. Ask the sender for anything missing.
3. Decide whether to act. If the decision is not clear, ask the owner and the legal
   adviser before recording anything: a takedown removes the file for every learner
   and cannot be undone in the application.
4. Choose the grounds learners will read: `copyright` (the copyright owner asked),
   `other_rights` (another right, such as privacy), or `unlawful` (the law does not
   allow us to keep it).

## 2. Identify the file

A takedown names the exact file by its SHA-256. Administrators cannot open learners'
media (SRS 2.2), so the file must come from the sender (or a copy they point to).

```sh
sha256sum the-file-from-the-notice.mp3
```

The fingerprint is `upload:` followed by the 64 hex characters. A re-encoded, trimmed
or otherwise changed copy has a different hash; record each distinct file the sender
identifies as its own takedown.

## 3. Record the takedown

Sign in as an administrator (a verified account in `LISTENUP_ADMIN_EMAILS`, ADR 0045).
With the browser's session cookie and CSRF token (in production the cookies carry the
`__Host-` prefix; locally they are `listenup_session` and `listenup_csrf`):

```sh
curl -sS -X POST https://<host>/api/v1/admin/takedowns \
  -H 'Content-Type: application/json' \
  -H "X-CSRF-Token: $CSRF" -H "Idempotency-Key: $(uuidgen)" \
  -b "__Host-listenup_session=$SESSION; __Host-listenup_csrf=$CSRF" \
  -d '{"fingerprint":"upload:<sha256>","grounds":"copyright",
       "reason":"<notice date, sender, our reference; no learner data>"}'
```

- 202: recorded; note the `id`. Removal runs in the background.
- 409 `takedown_exists`: this file is already taken down (`takedown_id` names it).
- 422: the fingerprint, grounds or reason is not valid.
- 404: the account is not an administrator.

The `reason` is internal and never shown to learners. Keep it short and factual.

## 4. Confirm it was carried out

`actioned_at` is set once every copy is removed. As the database owner or an operator
account:

```sql
SELECT id, fingerprint, grounds, received_at, actioned_at, report
  FROM ops.takedowns ORDER BY received_at DESC LIMIT 20;
```

`report` holds counts only: `media_removed`, `learners` and `objects_removed`. A
takedown left unactioned for more than a few minutes is usually waiting for a
conversion still writing a file: the job tries again every minute and the
`admin.reconcile_takedowns` schedule queues it again every 10 minutes. If it stays
unactioned, check `content.media_writes` and `practice.card_snippet_writes` and follow
the [content-deletion runbook](content-deletion.md#unresolved-conversion-writes);
never delete a writer registration because of its age. Failed jobs are listed at
`/admin/jobs` and can be retried there.

## 5. What learners see

- Affected learners keep the clip in their library with a "Removed" badge. Its page
  says it was removed and why (from the grounds), and that their sessions, marks and
  cards are kept. Learners online at the time also get a notice.
- The clip, its waveform and its card audio no longer play, and no new plan can start.
- Anyone who uploads the same file later sees it refused with `source_taken_down`.

## 6. Reply to the sender

Tell the sender the file has been removed and will be refused if added again. Do not
say who had it or how many learners did. Report counts only if the owner agrees.

## Limits

- Exact files only; there is no automated content matching.
- Transcripts of a removed clip stay, because learners' marks rely on them (ADR 0098).
  Ask the legal adviser if a notice requires the text to go as well.
- Do not downgrade migration `105_takedowns` while takedowns exist; it refuses to.
- There is no in-app way to reverse a takedown. A mistaken one needs the owner's
  decision and a reviewed database change, until #181 builds the reply process.
