# ADR 0067: Review saved cards and marks across sessions

Status: accepted (issue #75 plan approved)

## Context

FR-CA-5 requires a learner to hear a saved private snippet before revealing the
written and heard forms. Cards and snippets already exist (#72, #73). Review and
marks must follow the learner across sign-ins without introducing scheduling,
candidate suggestions, or a dependency on tags (#61 / PR #214).

## Decision

Reuse `GET /cards` and its newest-first `(created_at, id)` keyset pagination.
The authenticated `/cards` page uses `/cards/{id}/audio`; neither accessible
labels nor visible content include either form before an explicit reveal.
Reveal unlocks after the snippet ends. Pending, failed and legacy unavailable
snippets cannot unlock it; learners can move to another card or retry failed audio.

Append results to `practice.card_reviews`, with the three allowed values `heard`,
`unsure` and `missed`, a server timestamp and UUID. A composite card/learner foreign
key, learner RLS and SELECT/INSERT-only API grants protect the history. Deleting a
card or account cascades its history. POST uses the existing idempotency protocol;
a failed response can be retried with the same key. GET returns the latest 50
results for an owned card; exports include all review rows. Review history does
not affect practice-step progression or schedule another review.

`GET /marks` returns marks across the learner's sessions, newest first with
`(created_at, id)` keyset pagination and an index beginning with `user_id`.
It composes the existing mark/session relationship, without reading transcript
cache or depending on tags. Source URLs use `/contents/{id}?at_ms={absolute_ms}`
and the existing content player performs the seek. The authenticated `/marks`
page exposes source, status, note, creation time and source/session navigation.

All reads and result responses use private/no-store. Query caches and local
component state inherit the existing account-transition isolation. The header
wraps the main navigation below the wordmark/account controls on narrow screens.

## Consequences

Review data is server-owned and available to a second browser sign-in. Both
keyset lists remain bounded, and equal timestamps are ordered by UUID. The UI
cannot review an unavailable legacy snippet until audio exists; it explains this
and permits deck navigation. No spaced repetition or phrase suggestions are added.
