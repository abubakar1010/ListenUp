# ADR 0039: Google OIDC, verified-email linking and deletion confirmation

- Status: Accepted; Google request mechanism corrected by [ADR 0040](0040-google-session-age-and-callback-recovery.md)
- Date: 2026-10-16
- Sources: #32; FR-ACC-1, FR-ACC-2, FR-ACC-4, DR-1; ADRs 0006, 0029 and 0033
- Owner approved the implementation plan and the policies below on 2026-10-16.

## Decision

Use Authlib's authorization-code client with Google's fixed authorization, token
and JWKS endpoints, scopes `openid email`, PKCE S256, state and nonce. Validate
RS256 signatures, issuer, audience, expiry, issue time, authorized party and nonce;
require a nonempty subject, a valid email and the boolean `email_verified = true`.
Do not request offline access or persist provider access/refresh/ID tokens.

`identity.oauth_accounts` keys identities by `(provider, subject)` and cascades
from the user. Subject lookup precedes email lookup, so a changed provider email
never moves an existing identity. For an unlinked subject, a Google-verified email
is sufficient to link an existing account, including a locally unverified password
account. Preserve its password. Serialize subject/email decisions with transaction
advisory locks; retain the database uniqueness constraint as the final guard.

Google bypasses the password-attempt lockout, as UX-35 proposed; it does not clear
that lockout. Google starts have a separate IP counter using the configured login
limit/window. A linked identity whose account passed its deletion deadline is
refused until cascade purge removes the link. An unlinked subject may use an email
released by a gone account, matching the existing registration policy.

Store authentication transactions in `identity.oidc_flows`: hashed random state
and browser secrets, purpose, expiry, optional cascading user and short-lived flow
data. The PKCE verifier and nonce exist only in that expiring flow; provider tokens
are never stored. Narrow SECURITY DEFINER functions with fixed search paths and
revoked PUBLIC execution create/read/atomically consume flows. The API has only
learner-scoped SELECT access outside these functions. Consumption commits before
external calls or account transitions, so failures cannot make a callback reusable.
Expired flows cannot be read and are removed when the next flow is created.

Use Secure, HttpOnly, SameSite=Lax, host-only cookies outside local/test HTTP.
Starting another flow replaces the browser binding, safely invalidating an older
in-progress flow in that browser. Redirect destinations must be local paths;
callback responses use no-store and no-referrer. Application log formatting
redacts OIDC query secrets, including authorization codes and state.

Every sign-in ends in `Accounts.complete_sign_in`. A pending-deletion callback
starts no session and redirects to an explicit Restore/Keep it deleted question.
A browser-bound, expiring, single-use continuation permits the CSRF-protected
restore POST; the existing atomic deadline/request-lock rules still apply. Keep
it deleted consumes the continuation without restoring. Restore retains the
original local destination. No proof is carried in a URL or browser storage.

For account deletion, start a reauthentication flow bound to the current learner
and session with `prompt=login`, `max_age=0`. Require a fresh `auth_time` and the
same linked subject and session at callback. Issue a single-use, browser/session-
bound deletion proof in an HttpOnly cookie. Returning from Google does not delete
anything: the existing CSRF-protected `DELETE /me` still requires `confirm: true`.
A current password remains an independent option; stale Google cookies cannot
block it. Preserve the deletion notice, disabled sessions, grace period and purge.

Export linked identity data and flow metadata, omitting flow token/browser hashes
and all flow payload data. Both tables cascade on purge; other learners' rows
remain inaccessible through the API role.

## Configuration and verification

Set `LISTENUP_GOOGLE_CLIENT_ID`, `LISTENUP_GOOGLE_CLIENT_SECRET` and
`LISTENUP_GOOGLE_REDIRECT_URI` in the API environment. Register the exact redirect
URI with a Google Web application client; production must use HTTPS. The local
default uses the Vite proxy at
`http://localhost:5173/api/v1/auth/oidc/google/callback`. Missing credentials return
503 `google_unavailable`; the secret uses Pydantic SecretStr. Transaction lifetime
is `LISTENUP_OIDC_LIFETIME_SECONDS` (default 600, constrained to 60–900 seconds).

Automated tests mock token/JWKS responses with signed test ID tokens and cover
invalid claims/signatures, cancellation, replay, expiration, account linking,
concurrency, restore and deletion boundaries. Browser tests mock the API and do
not establish live Google interoperability. Live consent, deployment redirect,
provider reauthentication behavior and production cookie behavior require a real
configured Google client and HTTPS deployment; report them as unverified until run.
