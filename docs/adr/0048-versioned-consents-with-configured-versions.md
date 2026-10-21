# ADR 0048: Versioned consents with configured placeholder versions

- Status: Accepted
- Date: 2026-10-20
- Source: issue #104; [SRS FR-SH-17, NFR-SEC-4](https://claude.ai/code/artifact/fd47a9cb-6515-4fde-a232-3ab8cc14f0dd); [Software Architecture 8 (`identity.consents`) and 12.2](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13); [Database Design 3](https://claude.ai/code/artifact/ba05f7b3-f881-41e5-86d6-dcb94a509644); ADRs 0013, 0014, 0021, 0039 and 0040

## Context

We must be able to show which version of the Terms of Service and Privacy Policy each learner accepted, ask again when a version changes, and (for Shadow, #78) record voice-recording consent before the first recording and let the learner withdraw it. Database Design 3 defines `identity.consents` (one row per `(user_id, kind, version)`, `withdrawn_at` for withdrawal). The policy text and its versions belong to #103, which is not written yet.

## Decision

### Versions come from configuration

- `LISTENUP_TERMS_VERSION`, `LISTENUP_PRIVACY_VERSION` and `LISTENUP_VOICE_CONSENT_VERSION` name the current version of each document: labels of 1 to 20 characters from `A-Z a-z 0-9 . _ -` (the column holds 20). Versions are labels, not ordered numbers; a consent counts only for the exact current label (`modules/identity/domain/consents.py`).
- **Assumption until #103:** the defaults are `placeholder-1`, and `/terms` and `/privacy` show text marked as a placeholder. When #103 publishes the documents, it sets the real labels and replaces the pages. Changing a label is how a new version is published; no migration is needed.

### Sign-up

- `POST /auth/register` takes `terms_version` and `privacy_version`, the versions the form showed (from the public `GET /auth/consent-versions`). Without them it answers 422 `consent_required`; with a label that is no longer current, 409 `consent_version_changed` with the current labels, and nothing is created. The rows are written in the transaction that creates the account.
- Google sign-up (`GET /auth/oidc/google/start?terms_version=…&privacy_version=…`) stores the accepted labels in the browser-bound OIDC flow. The callback records them only when `identity.repository.google_account` **created** the account; a new account without the current labels is refused inside the callback's savepoint, so the user and Google link roll back, and the browser goes to `/auth/google-error?reason=consent`. Existing accounts, including a password account linked by verified email, sign in without accepting again here: they already hold rows, or are asked by the rule below.
- So every account created after this change holds terms and privacy rows with the then-current versions.

### A newer version on sign-in

- `Me.consents_required` lists `terms` and/or `privacy` when the learner holds no unwithdrawn row for the current label. The web app shows a prompt before any signed-in page (`auth/ConsentPrompt.tsx`); accepting calls `POST /me/consents {kind, version}` once per document (409 `consent_version_changed` for a label that is not current), and the learner can sign out instead. Accepting adds a row, so the history of accepted versions stays.
- The prompt appears on the next `/me` after the new label is deployed, which is the next sign-in or the next page load of an open session. It appears once: after accepting, nothing is outstanding.
- **The server enforces it (owner decision).** `CurrentLearner` refuses with 403 `consent_required` (listing `consents_required`) while terms or privacy are outstanding, so calling the API directly does not get past the prompt. The check reads at most one row per kind by primary key. Routes a learner who declines still needs take `SignedInLearner` instead, which resolves the session without the check: `GET /me`, `GET`/`POST /me/consents`, `POST /me/consents/withdraw`, the data export routes (`/me/exports…`), `GET /me/deletion-summary`, `DELETE /me` with its Google re-authentication, and the `GET /events` stream (ids only; it carries `account.disabled`). Sign-out needs no learner. A learner who declines can therefore export their data and delete the account as usual.
- The web app keeps `/settings` and `/settings/delete-account` open while consent is owed, and the prompt links to them. An open practice session (`/sessions/…`) is not replaced by the prompt, which would void a Blind listen without the leave warning; it shows once the server refuses one of the page's requests with `consent_required`, or on the next page. Accepting refetches the refused requests.

### Voice recording and withdrawal

- `voice_recording` uses the same table and endpoint. `POST /me/consents/withdraw {kind}` sets `withdrawn_at` on every unwithdrawn row of that kind; only voice recording can be withdrawn (409 `consent_not_withdrawable` for terms and privacy, which hold while the account exists). Granting a withdrawn version again clears `withdrawn_at` and renews `granted_at` (the primary key keeps one row per version, so an earlier withdrawal time of the same version is not kept; see Consequences).
- `identity.service.has_voice_consent(session, learner, settings)` and `require_voice_consent` (403 `voice_consent_required`) are the checks the Shadow module calls before starting a round (#79). They take the app's settings (`request.app.state.settings`), the labels `/me/consents` grants, run in the learner's row-level-security transaction and count only the current `LISTENUP_VOICE_CONSENT_VERSION`, so a new voice label asks again before the next round.
- What happens to recordings already made when voice consent is withdrawn is decided with Shadow (#78, #79); until then the withdrawal dialog promises only that new rounds will not record.

### Data rules

- `identity.consents` has the `own_rows` policy; `listenup_api` has SELECT, INSERT and UPDATE (no DELETE: rows go with the account through `ON DELETE CASCADE`). The rows are part of the learner's data export.
- Grants and withdrawals are idempotent by themselves, so they take no `Idempotency-Key`.

## Consequences

- Placeholder versions are recorded for every account created before #103. When #103 sets the real labels, every learner is asked once to accept them; that is the intended effect, not a migration.
- Production can start with the placeholder labels; nothing refuses them. The owner chose not to refuse them now: #103 decides whether to refuse placeholder labels outside local and test when it sets the real ones.
- Consent history is kept per version, not per event (owner decision): re-granting a withdrawn version overwrites its `granted_at` and clears `withdrawn_at`, so the gap between an earlier withdrawal and the new grant of the same version is not recorded. An append-only consent log would need a Database Design change.
- Every request through `CurrentLearner` costs one indexed consent read. A learner who owes consent and keeps a Dictation draft or Blind listen open loses what the refused requests would have saved.
- A Google learner who chose Continue with Google on the sign-in page without an account is sent to the create-account page to accept first, then repeats the Google step.
