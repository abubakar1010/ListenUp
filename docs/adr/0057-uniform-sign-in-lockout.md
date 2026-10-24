# ADR 0057: The sign-in lockout counts every address and says how many tries are left

- Status: Accepted by the owner for #194 (recommended choices, 2026-10-23)
- Date: 2026-10-23
- Implements: FR-ACC-2, NFR-SEC-1, NFR-USE-3; UX-35 (D17)
- Builds on: ADR 0014 (problem responses), the D17 lockout in `modules/identity`

## Context

D17 pauses sign-in for 15 minutes after 5 failed tries on an account. UX-35 asks the
interface to warn one try before the pause and to say the same words whether or not the
email has an account. Until now only real accounts were counted: an unknown email
answered `invalid_credentials` on every try, while a real one answered `account_locked`
on the 5th, so five requests revealed whether an address had an account. Showing a
tries-left count for real accounts only would reveal it one try earlier.

## Decision

- **Every address is counted.** A failed sign-in for an email without a live account
  (no account, or one deleted for good) is counted in `ops.rate_counters` under
  `login_fail:email:<digest>` and locked under `login_lock:email:<digest>`, with the
  same threshold, window and lock length as an account. Accounts keep their
  `user:<id>` keys, so success, password reset and the account purge clear them as
  before. The subject rules are pure functions in `identity/domain/lockout.py`.
- **The digest hides the address.** It is HMAC-SHA256 of the address (trimmed,
  case-folded) under `LISTENUP_ANALYTICS_HMAC_KEY`, with a `login-lock` domain prefix,
  cut to 32 hex characters. No readable part of the address is stored. The rows expire
  with the rate-counter retention (Database Design: windows older than 1 day).
- **Tries left.** Every `invalid_credentials` from `POST /auth/login` carries
  `attempts_left` (threshold minus failures in the window) and `lock_minutes` (the
  configured pause). The try that reaches the threshold answers 429 `account_locked`
  with `locked_until`, as before. Re-entering the password before deleting an account
  counts towards the same lock but does not add the fields (it answers
  `wrong_password`).
- **Interface.** The sign-in page warns at `attempts_left` 1 with the reset link, shows
  the paused state with the clock time, the minutes left (updated silently) and Reset
  password, and keeps Sign in focusable with `aria-disabled` while paused (UX-10, UX-35).

## Consequences

- The lockout no longer tells a stranger whether an account exists, and learners can
  stop before the pause.
- A refused sign-in for an unknown address now writes counter rows; the per-IP login
  limit still bounds how many a client can cause.
- The analytics HMAC key now has two uses, separated by the domain prefix. A dedicated
  key can replace it later; rotating it resets the counts for unknown addresses only.
