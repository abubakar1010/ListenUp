# ADR 0017: Password reset tokens are minted by the email job

- Status: Accepted
- Date: 2026-10-03

## Context

Password reset (FR-ACC-3, #31) emails a link holding a one-time token. The Database Design (section 3) stores secrets only as hashes, in `identity.one_time_tokens`. Slow work such as sending email runs in background jobs that are queued in the request's transaction (ADR 0015). Job arguments are stored as JSON in `procrastinate.procrastinate_jobs` and stay there after the job ends. If the request minted the token and passed it to an email job, the raw token would sit in the database next to its hash, which defeats the hash. Two more issues were left open:

- A reset link arrives before the learner is known, but `one_time_tokens` has a `user_id` and so falls under the `own_rows` policy (ADR 0013).
- The Architecture (9.2) lists a single `POST /auth/password-reset`, but a reset has two steps: asking for the email, and setting the new password.

## Decision

- The request only finds the account and queues `identity.send_password_reset` with the learner's id. The job mints the token, stores its SHA-256 with a one-hour expiry, ends the learner's older unused reset links, and then emails the link through `notifications/service.py`. The raw token exists only in the worker's memory and in the email. A retried run mints a new token and ends the earlier one, so the only working link is the one in the email that was sent last. A unique job key queues at most one waiting email per learner.
- The link is `<web>/reset-password#token=<token>`. The token sits in the URL fragment, which browsers never send to a server, so it stays out of access logs and `Referer` headers.
- `one_time_tokens` has the `own_rows` policy. The API role may only `SELECT` and `UPDATE` (no `INSERT`, because workers mint tokens). `identity.consume_one_time_token(hash, purpose)`, a `SECURITY DEFINER` function like `resolve_auth_session`, marks a live token used and returns its learner. The API then sets the learner for the rest of the request. The row lock makes a token work once even when two requests race.
- There are two endpoints: `POST /auth/password-reset` (`{email}`, which always answers 202 with the same message) and `POST /auth/password-reset/confirm` (`{token, password}`, which answers 204, or 400 `invalid_reset_link`). A completed reset ends every login session of the learner and clears the sign-in lockout.
- Requests are limited per IP (429) and per address. Past the address limit, a request is dropped without telling the caller, so the limit neither reveals which emails have accounts nor lets someone block a learner's own reset email with 429s.

## Consequences

Tokens never appear in the job queue, the logs or any table except as hashes. Email verification can reuse the table, the function and the job pattern with `purpose = 'verify_email'`. The Architecture's endpoint list should name `/auth/password-reset/confirm`. Response times differ slightly between known and unknown emails (one queued job), which is far below network noise. Tokens that are used or expired are still swept by the retention story (Database Design 10.3).
