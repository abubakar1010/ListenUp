# ADR 0051: Legal texts as versioned files the web app shows

- Status: Accepted
- Date: 2026-10-22
- Source: issue #103; [SRS FR-SH-17, NFR-SEC-4, NFR-SEC-5, NFR-AI-7, DR-1](https://claude.ai/code/artifact/fd47a9cb-6515-4fde-a232-3ab8cc14f0dd); ADRs 0029, 0030, 0037 and 0048

## Context

ADR 0048 records which version of the Terms of Service, Privacy Policy and voice-recording consent each learner accepted, using labels from `LISTENUP_TERMS_VERSION`, `LISTENUP_PRIVACY_VERSION` and `LISTENUP_VOICE_CONSENT_VERSION`. Until #103 those were `placeholder-1`, and `/terms` and `/privacy` showed placeholder text. #103 writes the texts. A recorded consent is only meaningful if the label names exactly the text the learner saw, and the texts must be reviewable by pull request like the design documents.

## Decision

- **One file per version.** `docs/legal/<kind>-<year>-<n>.md` (`terms-2026-1.md`, `privacy-2026-1.md`, `voice-2026-1.md`) holds the text of that label. A deployed label's file is never changed in meaning; a new text is a new file and a new label. `docs/legal/README.md` lists the current labels, the source in code or design of every value a text states, the owner notes where code and text differ, and the questions for the legal adviser.
- **The web app shows the same files.** `apps/web/src/features/legal/texts.ts` imports them with Vite's `?raw` and maps each label to its text. `LegalPage` asks `GET /auth/consent-versions` for the current label and shows that text, so the page and the recorded consent always name the same file. A label with no text in the build shows an error instead of another version. The dev server allows `../../docs/legal` (`server.fs.allow`); the production build inlines the text in the lazily loaded page chunk, so the initial bundle does not grow.
- **A small renderer, no Markdown dependency.** `LegalText.tsx` renders only what the files use: `#` to `###` headings, paragraphs, `- ` lists, `> ` notes, `**bold**`, and links to app paths (one leading `/`, so `//host` and `/\host` are refused) or `http(s)` addresses (any other link target stays plain text). A text that needs more must extend the renderer and its tests.
- **Stable URLs.** `/terms`, `/privacy` and the new `/voice-consent` (`DOCUMENTS.voice_recording.path`, previously `/privacy`). Sign-up and the consent prompt already link from `DOCUMENTS`. Nothing links to `/voice-consent` yet: the Shadow consent notice (#78) must link to it through `DOCUMENTS.voice_recording.path`.
- **Defaults are the 2026-1 drafts; placeholders are refused in production.** The configured defaults become `terms-2026-1`, `privacy-2026-1` and `voice-2026-1`. Outside `local` and `test`, `Settings` refuses a label containing `placeholder` (the choice ADR 0048 left to #103), as it refuses the shared analytics key.
- **Drafts say so.** Until the legal review, each text opens with a "Draft, not yet legally reviewed" note. The service is not public (#16, #155), so no learner accepts a draft in production; a text changed by the review ships as a new label (`-2`), which asks every learner again.

## Consequences

- Publishing a version takes a pull request with the file, the `texts.ts` entry and the configured label; forgetting the entry shows the error on the page rather than a wrong text.
- Old texts stay in the bundle so a learner can be shown what they accepted; the legal chunk grows with each version, which is small text.
- The 90-day recording deletion (D7), the 30-day YouTube copy clean-up and content deletion (#89) are stated as designed but not yet built; `docs/legal/README.md` tracks them, and the stories that build them must cite their settings there.
