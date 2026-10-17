# ADR 0040: Google session-age verification and browser callback recovery

- Status: Accepted implementation correction; live provider validation outstanding
- Date: 2026-10-17
- Source: PR #157 independent review P1/P2; #32; FR-ACC-1, FR-ACC-4, NFR-SEC-5
- Supersedes ADR 0039's `prompt=login` / `max_age=0` request mechanism only.
- Does not change approved email-linking, lockout, explicit restore or deletion policies.

## Provider contract

Google's [Security bundle](https://developers.google.com/identity/siwg/security-bundle)
explicitly states that it does not support Google Account reauthentication
requests. Its [OIDC parameter reference](https://developers.google.com/identity/openid-connect/openid-connect#authenticationuriparameters)
documents `none`, `consent` and `select_account` prompts, and an essential
`auth_time` claim request. Neither account selection nor consent establishes a
fresh Google authentication. A newly issued ID token's `iat` does not do so either.

Remove the unsupported login prompt and `max_age`. For deletion confirmation use
`prompt=select_account` only to choose the linked identity, and request
`claims={"id_token":{"auth_time":{"essential":true}}}`. Validate the signed
claim using the existing boundary: integer, not boolean, no earlier than the new
flow's start minus five seconds and no later than current time plus five seconds.
Keep all signature, issuer/audience, nonce, subject, session and single-use checks.
Missing, malformed, stale or future authentication time cannot create deletion
proof. Ordinary Google sign-in does not require this optional claim.

Because Google cannot be instructed to reauthenticate, the supported recovery is
explicit user action: sign out of the Google Account separately, keep ListenUp
open, start a new confirmation flow here, then sign into Google. This establishes
a new Google session after the new flow starts. Merely selecting an existing
Google session continues to fail closed. Do not automatically sign the user out
of Google, revoke provider credentials, collect Google passwords, substitute
consent for authentication or relax the freshness boundary.

## Required operator setup and release validation

In Google Auth Platform, use the intended project/client and confirm Audience's
publishing status is In production and Verification Center's status is Verified.
Then Settings → Advanced Settings → Session age claims must be enabled. These
are Google-side requirements in the Security bundle documentation, not settings
that the API can enable with an environment variable. Also supply the existing
client ID, secret and exact registered HTTPS redirect URI. Enabling Authentication
strength claims (`amr`) is not required by this implementation.

No live Google credentials or console access were supplied. Request-shape and
signed-response tests validate the documented contract but cannot demonstrate
real Google session creation or claim availability. **P1's live validation remains
a merge gate** until an operator records this complete test without retaining
credentials or raw tokens:

1. Confirm the production/verification/session-age prerequisites above.
2. Sign into ListenUp with a Google-only account; retain an older Google session.
3. Start deletion confirmation. Verify selecting that session produces no proof
   and leaves the account active, with clear recovery instructions.
4. Sign out of that Google Account in another tab. Leave ListenUp open.
5. Retry from the recovery page; sign into Google after the new flow starts.
6. Verify the signed auth_time is present and within the unchanged freshness
   boundary. Only then should the app show confirmation, while the account is
   still active. Choosing another subject must fail.
7. Tick the deletion checkbox and explicitly submit. Verify disabled sessions,
   pending deletion, and subsequent explicit Restore/Keep it deleted behavior.
8. Check deployed routing and Secure/HttpOnly/SameSite cookies over HTTPS.

Do not mark P1 fully validated or the PR ready to merge from mocked results alone.

## Browser recovery

Expected callback refusals redirect with 303 to the public `/auth/google-error`
page, outside the signed-in redirect guard. URLs carry only fixed reason/intent
codes, never the provider message, authorization code, state, token or identity.
The page supplies an announced message, a keyboard-operable control that starts a
new flow and an appropriate back link. Refreshing it cannot replay the callback.
For freshness refusals it explains the separate Google sign-out/new-sign-in steps.

A short-lived HttpOnly intent cookie is only a recovery hint when state is expired
or invalid. A valid consumed flow overrides it; it never establishes identity,
authenticates a request, relaxes matching or authorizes deletion. Every retry
still passes the normal authentication and rate-limit checks.

State consumption stays independently committed before provider/account work.
Business writes run in a savepoint, so converting a refusal into a redirect cannot
commit a partially created or linked account. Problem JSON remains appropriate
for fetch-based restore/deletion endpoints; their existing React error handling
is preserved. Callback responses retain no-store and no-referrer headers.

## Evidence

The new regression group failed before production edits (10 backend cases), as
did the three missing recovery-page cases. Provider mocks now omit `auth_time`
unless the outgoing request asks for it and simulated Google settings enable it.
Tests cover stale selection across retries, missing/invalid/future claims, fresh
Google session evidence, no deletion proof on denial, expired reauth routing,
callback replay, transaction rollback and safe public error URLs. Browser tests
navigate through an actual document redirect, reload the error page and activate
retry with the keyboard; provider/API responses remain mocked.
