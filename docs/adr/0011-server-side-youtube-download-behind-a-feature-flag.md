# ADR 0011: Server-side YouTube download, behind a feature flag

- Status: Accepted
- Date: 2026-10-03
- Source: [Software Architecture, section 13.1](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13)

## Context

Downloading YouTube media gives full playback control but conflicts with YouTube's terms; legal review is pending (OQ-6).

## Decision

Ship the upload-only path first. YouTube intake runs in the isolated media worker and stays behind `LISTENUP_YOUTUBE_INTAKE_ENABLED` (off by default) until the review clears it. YouTube media is excluded from data exports (D10).

## Consequences

The product launches without depending on the legal outcome; the downloader can be replaced or switched off without touching other code.
