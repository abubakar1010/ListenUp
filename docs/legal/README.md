# Legal documents

The Terms of Service, Privacy Policy and voice-recording consent notice (#103). Each file is one version of one document, named by its version label; the web app shows these same files at `/terms`, `/privacy` and `/voice-consent` ([ADR 0051](../adr/0051-legal-texts-as-versioned-files.md)).

| Document | Current label | Setting | File | Page |
| --- | --- | --- | --- | --- |
| Terms of Service | `terms-2026-1` | `LISTENUP_TERMS_VERSION` | [terms-2026-1.md](terms-2026-1.md) | `/terms` |
| Privacy Policy | `privacy-2026-2` | `LISTENUP_PRIVACY_VERSION` | [privacy-2026-2.md](privacy-2026-2.md) | `/privacy` |
| Voice recording consent | `voice-2026-2` | `LISTENUP_VOICE_CONSENT_VERSION` | [voice-2026-2.md](voice-2026-2.md) | `/voice-consent` |

## Status: drafts, not legally reviewed

All three are drafts. They have **not** been reviewed by a legal adviser, and each says so at the top. Issue #103 stays open until the review (ideally by the OQ-6 adviser) is done. Bracketed text (`[... to be completed ...]`) marks what the adviser or the owner must supply.

For this revision the owner approved updating the existing, undeployed `2026-1` drafts without changing the consent labels (2026-10-28). No configuration or consent-capture behavior changes. This is not permission to edit a label after learners have accepted it in a deployment. A text that changes after review is published as a new version (for example `privacy-2026-2`): a label a learner accepted always names the text they saw.

The owner instructed remediation of #249 on 2026-10-29. The affected retention
statements are published as new `2026-2` privacy and voice versions; old labels are
preserved regardless of deployment history. These remain unreviewed drafts.

The owner approved carrying the clip-deletion clarification into these current
`2026-2` drafts on 2026-10-31, preserving the `2026-1` texts. A follow-up check found
zero GitHub deployments, while #112 still records the live cutover as unverified.
No evidence of learner acceptance of `2026-2` was found in those sources; this does
not establish whether deployments outside GitHub have used these labels. The owner
must confirm whether any deployment has shown these labels to learners. Confirmed
prior acceptance requires new labels for meaningful changes.

## Publishing a new version

1. Add the new file (`<kind>-<year>-<n>.md`); never edit the text of a label already deployed, except for typo fixes that change no meaning.
2. Register it in `apps/web/src/features/legal/texts.ts`.
3. Change the default in `apps/api/src/listenup/platform/config.py` (or the deployment's `LISTENUP_*_VERSION`). Every learner is asked to accept terms or privacy on their next page load, and voice consent before their next Shadow round (ADR 0048).
4. Update the table above and the sources below.

Production refuses a label containing `placeholder` at start-up.

## Where each stated value comes from

Checked against `origin/main` at `1494640` on 2026-10-31, including #249 and #244. These are repository defaults and implementation sources, not verification of a running production deployment.

| Stated value | Source |
| --- | --- |
| Recordings deleted 90 days after recording; grades and word labels stay | D7 (issue #103, confirmed 2026-10-03); SRS FR-SH-17 and 8.1 (ShadowRound); System Design 6.3. Configured as `LISTENUP_SHADOW_RECORDING_RETENTION_DAYS` (default 90) and swept daily (#93, ADR 0087); reflected in the `2026-2` drafts |
| Deleted account disabled at once, restorable for 7 days, then purged | D9; SRS DR-1; ADR 0029; `account_deletion_grace_days = 7` in `apps/api/src/listenup/platform/config.py` |
| Signed out everywhere on deletion | ADR 0029 (every login session ends in the deleting transaction) |
| Export excludes YouTube media files, includes their links, titles and practice | D10; SRS NFR-SEC-5; ADR 0030; `NOTES` and module docstring in `apps/api/src/listenup/modules/export/domain/archive.py` |
| Export archive kept 7 days; three requests per UTC day | `export_keep_days = 7`, `export_daily_limit = 3` in `config.py`; ADR 0030 |
| AI providers must not train on data; hosted ones also need verified zero retention, region and population | NFR-AI-7, FR-BL-13, FR-SH-17; ADR 0037; `eligible()` in `apps/api/src/listenup/ai/policy.py` (refuses any entry whose `trains_on_inputs` is not `false`, and hosted entries without `retention_verified`, consent, region and population) |
| Default configuration: local faster-whisper transcription and wav2vec2 alignment; hosted AI and local text AI disabled | `apps/api/src/listenup/ai/ai.yaml`: `faster-whisper` and `wav2vec2-ctc` are local; `groq` has `enabled: false`, `retention_verified: false`; `ollama` is local and `enabled: false`; `speech_assessment: []` |
| Hosted text AI may grade gists, extract key points and, as a fallback, write Shadow feedback | `tasks` in `ai.yaml`: `extract_key_points` and `grade_gist` list `groq` first, `shadow_feedback` lists `ollama` then `groq` (ADR 0037, ADR 0046) |
| Hosted text AI receives transcript, key points and gist, or a round's number, scores and flagged words; never audio or identifiers | SRS FR-BL-13; `GradeGistInput`, `ExtractKeyPointsInput` and `ShadowFeedbackInput` in `apps/api/src/listenup/ai/tasks.py`; `CallContext` in `ai/policy.py` carries no learner identity. See owner note 10 |
| Password stored as a salted Argon2id hash | NFR-SEC-1; `apps/api/src/listenup/modules/identity/passwords.py` |
| Sign-in session lasts at most 30 days; user agent and IP kept with it | `session_days = 30` in `config.py`; `user_agent` and `ip` in `apps/api/src/listenup/modules/identity/models.py` |
| Upload limits 500 MB per file, 2 GB per account (binary units) | `upload_max_bytes`, `upload_quota_bytes` in `config.py`; ADR 0020; D5 |
| Unconfirmed upload expires after 24 hours | `upload_confirm_hours = 24` in `config.py` |
| 120 minutes of new audio per day | `intake_daily_minutes = 120` in `config.py`; ADR 0027 |
| Original upload deleted after conversion | ADR 0022 |
| YouTube intake switched off | `youtube_intake_enabled = False` in `config.py`; ADR 0011; OQ-6 |
| YouTube copies shared between learners and deleted 30 days after last use | System Design 6.2 and 6.3. **Clean-up not built yet**; drafts disclose this: see owner note 2 |
| Deleting a clip removes its sessions, marks, cards, recordings and corrections | SRS DR-2. Clip deletion built in #89 (merged in #244; `DELETE /contents/{content_id}`, ADR 0085; [runbook](../runbooks/content-deletion.md)): confirmed in the library, with private files and rows removed by a background job. Shared media and caches are only released; their orphan sweep is not built yet (#93). Backups expire separately. The current `2026-2` drafts describe clip deletion; **single-session and single-recording deletion are not built yet** (#90): see owner notes 1, 6 and 7 |
| Usage events keep ids only, outlive clip and session deletion, go with the account | SRS DR-2; ADR 0035 |
| Application backup dumps kept 14 days; provider backups unconfirmed | `backup_retention_days = 14` in `config.py`; ADR 0032 |
| Links to media expire after minutes | `signed_url_ttl_seconds = 300` in `config.py`; NFR-SEC-2 |
| Uploads checked for type and size and scanned | NFR-SEC-3; ADR 0049 |
| Withdrawing voice consent stops new recordings only | ADR 0048 ("until then the withdrawal dialog promises only that new rounds will not record"); `ConsentsSection.tsx` |
| Shadow can be skipped | CLAUDE.md (Card and Shadow can be skipped after confirmation); FR-SH-7 |
| No third-party analytics; cookies for sign-in, Google sign-in flow and CSRF | ADR 0035; the only cookies are the session cookie (`identity/service.py`), the Google sign-in flow cookie `listenup_oidc` (`identity/oidc.py`) and the CSRF cookie (`platform/csrf.py`) |
| Takedown notices reviewed, content removed or disabled, the learner told and able to reply; accounts that break the terms may be closed with a reason | SRS 2.2 (the Administrator handles abuse and takedown requests); Architecture 4.1 (`admin`: takedown records) and 9.2 (`POST /admin/takedowns`). **Not built yet** (#105, #181); explicitly marked as intended in the terms: see owner note 11 |

## Owner notes: where the code and the stated value differ

The owner approved the 2026-10-28 plan to retain D7 as the intended policy while explicitly disclosing the missing expiry implementation in the learner-facing drafts. Neither this documentation nor the existing draft labels establish that the service is ready for public launch.

1. **Recording expiry is implemented.** #93 (ADR 0087) supplies the configurable
   90-day default and daily sweep. `privacy-2026-2` and `voice-2026-2` describe this
   behavior and distinguish individual recording/session deletion, still owned by #90.
   Earlier `2026-1` labels remain unchanged and registered. This is narrow retention
   synchronization in #249, not a restart of #103 or legal clearance. Both current
   drafts also describe deleting a clip's recordings, separately from expiry.
2. **YouTube copies' 30-day clean-up is not built** (ADR 0029 consequences). YouTube intake is off, so no copy exists; the text describes the rule for when it is switched on.
3. **Sub-processors are placeholders.** [ADR 0073](../adr/0073-stage-0-host-oracle-always-free-arm.md) proposes Oracle Cloud for the stage-0 host but remains Proposed pending provisioning. It does not establish the deployed processor or region. Confirm actual hosting/database, storage, email, backup providers and locations before filling the policy; do not treat a proposed host as a verified sub-processor.
4. **Application backup dumps have a 14-day retention default**, separate from live-service purging. The policy no longer promises that all copies are gone after the 7-day grace period. Additional infrastructure/provider backup retention is unconfirmed; see adviser question 14.
5. **Server log retention is not specified** in the design or configuration.
6. **Withdrawing voice consent does not delete existing recordings**; individual recording/session deletion (#90) is not available yet, and clip deletion (#89, #244) does not run on withdrawal. Account deletion is available. Whether withdrawal should additionally offer deletion remains an owner/legal question; no such behavior is added here.
7. **Deleting a session or a single recording is not built yet** (#90). Clip
   deletion is built (#89, #244) and both current `2026-2` drafts describe library
   confirmation, background removal and separate backup expiry. Shared YouTube media
   and caches are only released, not removed by clip deletion; the orphan sweep
   remains in #93, as the privacy policy discloses (ADR 0085). Recording expiry is
   already implemented separately (owner note 1).
8. **Expired unconfirmed uploads**: nothing deletes the stored file of an upload that was never confirmed; the policy says only that it is not added to the library.
9. **Login session rows** (with IP and user agent): #93 deletes expired rows in a daily sweep; the policy states the maximum 30-day sign-in lifetime.
10. **The sources disagree on what hosted text AI may receive.** SRS FR-BL-13 lists the transcript, key points and gist; `ai/tasks.py` also sends Shadow round measures and flagged words (`shadow_feedback`, with `groq` as its fallback in `ai.yaml`). The privacy policy discloses both. The owner must either amend FR-BL-13 or remove `groq` from `shadow_feedback`, and then update the policy.
11. **Takedown handling and account closure are not built.** `modules/admin` has no takedown records or `POST /admin/takedowns`, and nothing tells a learner why content was removed or an account closed. The terms explicitly identify this as an intended process awaiting implementation and legal review. #105 builds recording a takedown, removing the media for every learner, blocking it from being added again and telling affected learners; #181 builds the learner's reply to a removal and the suspension or closure of an account with its reason. Both must be done before launch, and each must cite its settings and code in the table above.

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


## Validation for this revision

This is a documentation-only revision implementing FR-SH-17, FR-BL-13,
NFR-SEC-4, NFR-SEC-5, NFR-AI-7 and DR-1 disclosures. There are no executable,
configuration, schema or consent-version changes. Per `docs/testing.md`, artificial
Red tests and changed-executable-line coverage do not apply. Existing legal-page,
renderer, sign-up consent and Shadow readiness tests exercise the raw-file loading,
exact-version selection, stable links, missing-version failure and explicit agreement.
Actual commands and outcomes are recorded in the pull request. Legal review remains
outstanding in #102, and #103 must remain open until its review criterion is met.

This clip-deletion follow-up changes only this source register and the current
`2026-2` privacy and voice-recording drafts. The `2026-1` texts are preserved. Existing
`texts.ts`, `LegalPage`, `DOCUMENTS`, sign-up and Shadow readiness already load/link
these files. No additional registry or route is required.
