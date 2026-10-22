# Privacy Policy

Version privacy-2026-1, draft of 22 October 2026.

> **Draft, not yet legally reviewed.** This text describes how ListenUp is built today. It has not been reviewed by a legal adviser and may change before ListenUp opens to the public. A changed text gets a new version, and you will be asked to accept it.

ListenUp helps you practise listening to English. To do that it stores what you add and what you do in practice. This policy says what we keep, why, for how long, who processes it, and how you can take it with you or delete it.

[Operator name, address and contact email: to be completed before launch.]

## The short version

- Your clips, recordings and texts are used only for your own practice. We never sell or share them, and never use them to train AI models.
- AI services see your text or audio only if they do not train on it. Most of the processing runs on our own servers.
- Voice recordings are deleted 90 days after you make them.
- You can download a copy of your data at any time, and delete your account. A deleted account can be restored for 7 days; after that everything is removed.

## What we keep

**Your account.** Your email address, a display name if you set one, and either a password (stored only as a salted Argon2id hash, never as the password itself) or the link to your Google account if you sign in with Google. We also keep which version of these terms, this policy and the voice-recording notice you accepted, and when.

**Sign-in sessions.** For each signed-in browser we keep a session, the browser's user agent and the IP address it signed in from, so you stay signed in and we can protect your account. A session lasts at most 30 days.

**Clips you add.** Files you upload, converted for playback, with their title and length. The original file is deleted once it has been converted. Each file can be up to 500 MB, and each account can store up to 2 GB of uploads.

**YouTube links.** Adding clips from YouTube links is switched off for now. If it is switched on later, the video is downloaded to our servers so the player can control playback; that copy is shared by every learner who adds the same video, and its transcript is shared too.

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

Grading and transcription use AI. Every AI service is chosen in our own configuration, and a service is used for your recordings, transcripts or gists only if it does not train on them. A service that might train on them is never used; an open-source model on our own servers is used instead.

Today, all of this runs on our own servers:

- **Transcription** of clips: an open-source speech model (faster-whisper).
- **Word timing**: an open-source alignment model (wav2vec2).
- **Text feedback** (gist grading, key points, Shadow feedback): an open-source model run on our servers when it is switched on.

A hosted text service may be used later for gist grading and key points, and for written Shadow feedback when our own model cannot give it. It is used only if its terms exclude training on your data, it keeps no copy of it (zero data retention), and it serves your region. For gist grading and key points it receives the passage's transcript, its key points and your gist; for Shadow feedback it receives the round number, the round's scores and the words flagged in it, never the recording. It never receives your email or account details. Before a hosted service is switched on, it is added to the list below.

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
- **Voice recordings**: deleted 90 days after recording, or sooner if you delete the session or your account. The grades and word labels from a round stay with your session.
- **YouTube video copies** (if YouTube links are switched on): deleted 30 days after no session uses them; titles and transcripts stay.
- **Uploads you never finished**: an upload that is not confirmed within 24 hours is not added to your library.
- **Data export archives**: deleted 7 days after they are ready.
- **Usage events**: until your account is deleted. Deleting a clip or a session keeps its events, which hold ids only.
- **Backups**: nightly database backups are kept for 14 days, so data you delete can remain in a backup for up to 14 days after it is removed.
- **Server logs**: [period to be set before launch].

## Your choices and rights

**Download your data.** In Settings you can ask for a copy of your data. We build a ZIP file with all your data and your uploaded clips; it is ready to download for 7 days. YouTube video files are not included, but your YouTube clips' links, titles and practice are. You can ask for up to three exports a day.

**Delete your account.** In Settings you can delete your account. It is disabled at once and you are signed out everywhere. If you sign in within 7 days, you can choose to restore it, with everything as it was. After 7 days, your account, data, clips and recordings are deleted for good.

**Delete content.** Deleting a clip removes its sessions, marks, recordings and transcript corrections.

**Withdraw voice-recording consent.** In Settings you can withdraw your consent at any time. New Shadow rounds will then not record until you agree again.

[Rights under the applicable law, how to exercise them and how to complain to a supervisory authority: to be completed by the legal adviser.]

## Security

All traffic uses HTTPS. You can see only your own clips, sessions and recordings, and the database enforces this for every request. Media is delivered through links that expire after a few minutes. Uploaded files are checked for type and size and scanned before they are processed.

## Children

[Minimum age: to be completed by the legal adviser.]

## Changes to this policy

When this policy changes, it gets a new version and you are asked to accept it the next time you use ListenUp.
