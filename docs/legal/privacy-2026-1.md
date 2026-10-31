# Privacy Policy

Version privacy-2026-1, draft updated 28 October 2026.

> **Draft, not yet legally reviewed.** DRAFT — pending the legal review in #102. This text describes how ListenUp is built today. It has not been reviewed by a legal adviser and may change before ListenUp opens to the public. A changed text gets a new version, and you will be asked to accept it.

ListenUp helps you practise listening to English. To do that it stores what you add and what you do in practice. This policy says what we keep, why, for how long, who processes it, and how you can take it with you or delete it.

[Operator name, address and contact email: to be completed before launch.]

## The short version

- Your clips, recordings and texts are used only for your own practice. We never sell them or publish them to other learners, and never use them to train AI models. Processing for your practice is described below.
- AI services see your text or audio only if they do not train on it. Most of the processing runs on our own servers.
- The recording-retention policy is deletion 90 days after recording; automatic deletion is not implemented yet. See the retention section below.
- You can download a copy of your data at any time, and delete your account. A deleted account can be restored for 7 days; after that account purging removes your data from the live service. Backup copies are described below.

## What we keep

**Your account.** Your email address, a display name if you set one, and either a password (stored only as a salted Argon2id hash, never as the password itself) or the link to your Google account if you sign in with Google. We also keep which version of these terms, this policy and the voice-recording notice you accepted, and when.

**Sign-in sessions.** For each signed-in browser we keep a session, the browser's user agent and the IP address it signed in from, so you stay signed in and we can protect your account. A session lasts at most 30 days.

**Clips you add.** Files you upload, converted for playback, with their title and length. The original file is deleted once it has been converted. Each file can be up to 500 MB, and each account can store up to 2 GB of uploads.

**YouTube links.** Adding clips from YouTube links is switched off by a feature flag pending the legal review of server-side downloading, transcripts and uploads (OQ-6, #102). If it is switched on later, the video is downloaded to our servers so the player can control playback; that copy is shared by every learner who adds the same video, and its transcript is shared too.

**Transcripts.** We generate and store transcripts of your passages, with word timings and your transcript corrections, to support listening practice and feedback. Shadow uses the reference transcript for its segment. Planned Shadow analysis also processes your recording with the reference transcript and original audio; Shadow grading is not enabled yet.

**Your practice.** The passages you choose, your progress through each plan, what you type in Dictation, the gists you write in Blind, the places you mark in the transcript, your cards, and the grades and feedback you receive.

**Voice recordings.** In the Shadow step, each round records your voice while the original plays. You are asked for your consent before the first recording; see the [voice-recording notice](/voice-consent).

**Usage events.** We record events such as "a plan was started" or "a step was completed", tied to your account by an id only. They hold no text you typed and no content. We use them to see whether the product helps learners.

**Emails.** We send email only for your account: password resets and the confirmation when you delete your account.

We do not use advertising or third-party analytics. The only cookies are the ones that keep you signed in and protect forms from cross-site requests.

## Why we keep it

- To give you the service you signed up for: your library, your practice plans, grading and feedback, and your progress on any browser.
- To keep your account and the service secure, for example by limiting sign-in attempts.
- To improve ListenUp from usage events that contain no content.

[Legal basis for each purpose: to be completed by the legal adviser.]

## AI processing

Transcription and available grading use AI. Shadow recordings are currently stored for private replay; automated Shadow grading and comparison are not enabled, so feedback is unavailable. The planned speech analysis processes recordings and reference transcripts on our own servers. Every AI service is chosen in our own configuration, and a service is used for your recordings, transcripts or gists only if it does not train on them. A service that might train on them is never used; an open-source model on our own servers is used instead.

The repository default configuration uses local speech processing and disables hosted AI and text feedback:

- **Transcription** of clips: an open-source speech model (faster-whisper).
- **Word timing**: an open-source alignment model (wav2vec2).
- **Text feedback** (gist grading, key points, Shadow feedback): the configured local model and hosted alternative are both disabled pending their acceptance checks. A configured model is not evidence that feedback is available.

A hosted text service may be used later for gist grading and key points, and for written Shadow feedback when our own model cannot give it. It is used only if its terms exclude training on your data, it keeps no copy of it (zero data retention), and it is approved for your region and age group, with the required consent. Recordings are not sent to a hosted speech service under the current architecture. For gist grading and key points it receives the passage's transcript, its key points and your gist; for Shadow feedback it receives the round number, the round's scores and the words flagged in it, never the recording. It never receives your email or account details. Before a hosted service is switched on, it is added to the list below.

## Who processes your data

[Sub-processors to be completed before launch. Each will be named here with what it processes and where.]

- **Hosting and database**: [provider and region to be chosen].
- **File storage** (clips, recordings, exports, backups): [provider and region to be chosen].
- **Email delivery**: [provider to be chosen].
- **Google**: only if you choose to sign in with Google, which tells us your email address and Google account id.
- **Hosted AI services**: none today; see "AI processing".

## How long we keep it

- **Account and practice**: until you delete them or your account.
- **Uploaded clips**: until you delete them.
- **Voice recordings**: the policy is to delete them 90 days after recording, on request, or when the session or clip is deleted, whichever comes first. Grades and word labels stay after recording expiry. Account deletion has the separate 7-day grace period below. Automatic recording expiry and individual recording, session and clip deletion are not implemented yet (#89, #90, #93); this draft does not promise that these controls are available. They are required before public launch.
- **YouTube video copies**: the intended policy is deletion 30 days after last use; the cleanup is not implemented and YouTube intake remains disabled. Transcript retention is subject to the OQ-6 review.
- **Uploads you never finished**: an upload that is not confirmed within 24 hours is not added to your library.
- **Data export archives**: deleted 7 days after they are ready.
- **Usage events**: until your account is deleted. Deleting a clip or a session keeps its events, which hold ids only.
- **Backups**: the application backup setting keeps nightly database dumps for 14 days. Deleted data can remain in these copies until they expire. Any additional hosting-provider backup retention must be confirmed before launch; the 7-day account restore window does not erase backup copies.
- **Server logs**: [period to be set before launch].

## Your choices and rights

**Download your data.** In Settings you can ask for a copy of your data. We build a ZIP file with all your data and your uploaded clips; it is ready to download for 7 days. YouTube video files are not included, but your YouTube clips' links, titles and practice are. You can ask for up to three exports per UTC day. Only one export can be pending or building at once. A download link expires after 120 seconds; you can request another while the archive is available.

**Delete your account.** In Settings you can delete your account. It is disabled at once and you are signed out everywhere. If you sign in within 7 days, you can choose to restore it, with everything as it was. After the grace period, background purging removes your account, data, clips and recordings from the live service. Backup copies expire separately as described above. Signing in alone does not restore an account: you must choose Restore; choosing Keep it deleted preserves its deletion schedule.

**Delete content.** The intended controls remove a recording on request, or remove a clip together with its sessions, marks, recordings and transcript corrections. These individual deletion controls are not implemented yet (#89, #90). An upload transcript goes with its clip; a shared transcript is removed only when no learner still uses its media. Usage events remain until account deletion. Account deletion is available in Settings.

**Withdraw voice-recording consent.** In Settings you can withdraw your consent at any time. New Shadow rounds will then not record until you agree again.

[Rights under the applicable law, how to exercise them and how to complain to a supervisory authority: to be completed by the legal adviser.]

## Security

Production deployment requires HTTPS. You can see only your own clips, sessions and recordings, and the database enforces this for every request. Media is delivered through links that expire after a few minutes. Uploaded files are checked for type and size and scanned before they are processed.

## Children

[Minimum age: to be completed by the legal adviser.]

## Changes to this policy

When this policy changes, it gets a new version and you are asked to accept it the next time you use ListenUp.
