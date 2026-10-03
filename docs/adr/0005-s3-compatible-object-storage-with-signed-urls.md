# ADR 0005: S3-compatible object storage with signed URLs

- Status: Accepted
- Date: 2026-10-03
- Source: [Software Architecture, section 13.1](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13)

## Context

Media, recordings and card snippets are large binary files that the browser must stream with range requests.

## Decision

Store files in any S3-compatible store behind a private bucket. The browser receives short-lived signed URLs after an ownership check; media never passes through the API.

## Consequences

Portable across providers, no public bucket. Local development uses an S3-compatible container (ADR 0012).
