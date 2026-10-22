# Legal documents

The Terms of Service, Privacy Policy and voice-recording consent notice (#103). Each file is one version of one document, named by its version label; the web app shows these same files at `/terms`, `/privacy` and `/voice-consent` ([ADR 0051](../adr/0051-legal-texts-as-versioned-files.md)).

| Document | Current label | Setting | File | Page |
| --- | --- | --- | --- | --- |
| Terms of Service | `terms-2026-1` | `LISTENUP_TERMS_VERSION` | [terms-2026-1.md](terms-2026-1.md) | `/terms` |
| Privacy Policy | `privacy-2026-1` | `LISTENUP_PRIVACY_VERSION` | [privacy-2026-1.md](privacy-2026-1.md) | `/privacy` |
| Voice recording consent | `voice-2026-1` | `LISTENUP_VOICE_CONSENT_VERSION` | [voice-2026-1.md](voice-2026-1.md) | `/voice-consent` |

## Status: drafts, not legally reviewed

All three are drafts. They have **not** been reviewed by a legal adviser, and each says so at the top. Issue #103 stays open until the review (ideally by the OQ-6 adviser) is done. Bracketed text (`[... to be completed ...]`) marks what the adviser or the owner must supply.

Nothing is public yet (#16, #155), so no learner accepts these drafts in production. A text that changes after review is published as a new version (for example `privacy-2026-2`): a label a learner accepted always names the text they saw.

## Publishing a new version

1. Add the new file (`<kind>-<year>-<n>.md`); never edit the text of a label already deployed, except for typo fixes that change no meaning.
2. Register it in `apps/web/src/features/legal/texts.ts`.
3. Change the default in `apps/api/src/listenup/platform/config.py` (or the deployment's `LISTENUP_*_VERSION`). Every learner is asked to accept terms or privacy on their next page load, and voice consent before their next Shadow round (ADR 0048).
4. Update the table above and the sources below.

Production refuses a label containing `placeholder` at start-up.

## Where each stated value comes from

Checked against `main` at `2800167` on 2026-10-22.

| Stated value | Source |
| --- | --- |
| Recordings deleted 90 days after recording; grades and word labels stay | D7 (issue #103, confirmed 2026-10-03); SRS FR-SH-17 and 8.1 (ShadowRound); System Design 6.3. **Not configured in code yet**: see owner note 1 |
| Deleted account disabled at once, restorable for 7 days, then purged | D9; SRS DR-1; ADR 0029; `account_deletion_grace_days = 7` in `apps/api/src/listenup/platform/config.py` |
| Signed out everywhere on deletion | ADR 0029 (every login session ends in the deleting transaction) |
| Export excludes YouTube media files, includes their links, titles and practice | D10; SRS NFR-SEC-5; ADR 0030; `NOTES` and module docstring in `apps/api/src/listenup/modules/export/domain/archive.py` |
| Export archive kept 7 days; three requests per UTC day | `export_keep_days = 7`, `export_daily_limit = 3` in `config.py`; ADR 0030 |
| AI providers must not train on data; hosted ones also need verified zero retention, region and population | NFR-AI-7, FR-BL-13, FR-SH-17; ADR 0037; `eligible()` in `apps/api/src/listenup/ai/policy.py` (refuses any entry whose `trains_on_inputs` is not `false`, and hosted entries without `retention_verified`, consent, region and population) |
| No hosted AI service in use today; transcription faster-whisper, alignment wav2vec2, text AI self-hosted | `apps/api/src/listenup/ai/ai.yaml`: `faster-whisper` and `wav2vec2-ctc` are local; `groq` has `enabled: false`, `retention_verified: false`; `ollama` is local and `enabled: false`; `speech_assessment: []` |
| Hosted text AI may grade gists, extract key points and, as a fallback, write Shadow feedback | `tasks` in `ai.yaml`: `extract_key_points` and `grade_gist` list `groq` first, `shadow_feedback` lists `ollama` then `groq` (ADR 0037, ADR 0046) |
| Hosted text AI receives transcript, key points and gist, or a round's number, scores and flagged words; never audio or identifiers | SRS FR-BL-13; `GradeGistInput`, `ExtractKeyPointsInput` and `ShadowFeedbackInput` in `apps/api/src/listenup/ai/tasks.py`; `CallContext` in `ai/policy.py` carries no learner identity. See owner note 10 |
| Password stored as a salted Argon2id hash | NFR-SEC-1; `apps/api/src/listenup/modules/identity/passwords.py` |
| Sign-in session lasts at most 30 days; user agent and IP kept with it | `session_days = 30` in `config.py`; `user_agent` and `ip` in `apps/api/src/listenup/modules/identity/models.py` |
| Upload limits 500 MB per file, 2 GB per account (binary units) | `upload_max_bytes`, `upload_quota_bytes` in `config.py`; ADR 0020; D5 |
| Unconfirmed upload expires after 24 hours | `upload_confirm_hours = 24` in `config.py` |
| 120 minutes of new audio per day | `intake_daily_minutes = 120` in `config.py`; ADR 0027 |
| Original upload deleted after conversion | ADR 0022 |
| YouTube intake switched off | `youtube_intake_enabled = False` in `config.py`; ADR 0011; OQ-6 |
| YouTube copies shared between learners and deleted 30 days after last use | System Design 6.2 and 6.3. **Clean-up not built yet**: see owner note 2 |
| Deleting a clip removes its sessions, marks, recordings and corrections | SRS DR-2. **Content and session deletion not built yet** (#89): see owner note 7 |
| Usage events keep ids only, outlive clip and session deletion, go with the account | SRS DR-2; ADR 0035 |
| Backups kept 14 days | `backup_retention_days = 14` in `config.py`; ADR 0032 |
| Links to media expire after minutes | `signed_url_ttl_seconds = 300` in `config.py`; NFR-SEC-2 |
| Uploads checked for type and size and scanned | NFR-SEC-3; ADR 0049 |
| Withdrawing voice consent stops new recordings only | ADR 0048 ("until then the withdrawal dialog promises only that new rounds will not record"); `ConsentsSection.tsx` |
| Shadow can be skipped | CLAUDE.md (Card and Shadow can be skipped after confirmation); FR-SH-7 |
| No third-party analytics; cookies only for sign-in and CSRF | ADR 0035; the only cookies are the session cookie (`identity/service.py`), the Google sign-in flow cookie `listenup_oidc` (`identity/oidc.py`) and the CSRF cookie (`platform/csrf.py`) |
| Takedown notices reviewed, content removed or disabled, the learner told and able to reply; accounts that break the terms may be closed with a reason | SRS 2.2 (the Administrator handles abuse and takedown requests); Architecture 4.1 (`admin`: takedown records) and 9.2 (`POST /admin/takedowns`). **Not built yet** (#105, #181): see owner note 11 |

## Owner notes: where the code and the stated value differ

The owner chose to state the design value and track the gap (#103 plan approval, 2026-10-22).

1. **90-day recording deletion is not configured.** The Shadow module is empty and no setting or job deletes recordings. No recording can be made before Shadow ships, so the text states D7; the Shadow stories (#78, #79) must add the deletion job and a setting, and this table must then cite it.
2. **YouTube copies' 30-day clean-up is not built** (ADR 0029 consequences). YouTube intake is off, so no copy exists; the text describes the rule for when it is switched on.
3. **Sub-processors are placeholders.** Hosting, storage and email providers are not chosen (#16). They must be named before launch.
4. **Backups keep deleted data for up to 14 days**, which DR-1 does not mention; the policy discloses it.
5. **Server log retention is not specified** in the design or configuration.
6. **Withdrawing voice consent does not delete existing recordings**; FR-SH-17's "on request" deletion is met only by deleting the session, clip or account, which needs #89. Whether withdrawal should offer to delete recordings is open for #78/#79.
7. **Deleting a clip or session is not built yet** (#89); the texts describe DR-2.
8. **Expired unconfirmed uploads**: nothing deletes the stored file of an upload that was never confirmed; the policy says only that it is not added to the library.
9. **Login session rows** (with IP and user agent): no clean-up of expired rows was found; the policy says only that a session lasts at most 30 days.
10. **The sources disagree on what hosted text AI may receive.** SRS FR-BL-13 lists the transcript, key points and gist; `ai/tasks.py` also sends Shadow round measures and flagged words (`shadow_feedback`, with `groq` as its fallback in `ai.yaml`). The privacy policy discloses both. The owner must either amend FR-BL-13 or remove `groq` from `shadow_feedback`, and then update the policy.
11. **Takedown handling and account closure are not built.** `modules/admin` has no takedown records or `POST /admin/takedowns`, and nothing tells a learner why content was removed or an account closed. The terms describe the intended process. #105 builds recording a takedown, removing the media for every learner, blocking it from being added again and telling affected learners; #181 builds the learner's reply to a removal and the suspension or closure of an account with its reason. Both must be done before launch, and each must cite its settings and code in the table above.

## Questions for the legal adviser

1. Who is the operator (legal entity, address, contact), and which law governs the terms?
2. Which data-protection regimes apply (for example GDPR or UK GDPR), and what is the legal basis for each purpose in the privacy policy?
3. Minimum age, and whether minors need parental consent. Groq's terms require 18+ cloud access and leave application use by minors unconfirmed (ADR 0037); minors are routed to local models.
4. Are voice recordings biometric or special-category data here? Is the voice-consent notice sufficient as explicit consent, and must withdrawal also delete existing recordings?
5. Is the takedown process (notice, review, removal, learner reply) adequate, and is a designated agent or counter-notice process required?
6. Is it adequate to disclose that backups keep deleted data for 14 days?
7. Do usage events kept after clip or session deletion (ids only) need separate disclosure or consent?
8. Must sub-processors be listed by name before launch, and must learners be notified of changes to the list?
9. Hosted AI (Groq) retained-data location is the US: is an international-transfer mechanism needed, and does zero data retention change that?
10. Wording of "AI feedback may be wrong" and the warranty and liability clauses.
11. Server-side YouTube downloading remains under the OQ-6 review; the terms describe it as switched off.
12. Are the unverified-draft banners acceptable while the service is not public, and must accepted draft versions be re-accepted after review (the plan is yes, via new labels)?
13. Hosted AI is also gated on the learner's consent and population (age group) in `ai/policy.py`; must the policy say so?
14. Backups: ADR 0032 also relies on the managed database tier's own backups, whose retention is not set. Is "kept for 14 days" complete, and is "deleted for good" after the 7-day restore period accurate next to it?
