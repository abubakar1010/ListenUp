# ADR 0003: React single-page app, not server-rendered

- Status: Accepted
- Date: 2026-10-03
- Source: [Software Architecture, section 13.1](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13)

## Context

The product is a logged-in, media-heavy practice app; search indexing of practice screens is not needed.

## Decision

Build the web client as a React + TypeScript single-page app with Vite, served as static files from a CDN.

## Consequences

Free static hosting and a simple deploy. Revisit if public, search-indexed pages are needed.
