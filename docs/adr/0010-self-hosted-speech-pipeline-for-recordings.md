# ADR 0010: Self-hosted speech pipeline for recordings

- Status: Accepted
- Date: 2026-10-03
- Source: [Software Architecture, section 13.1](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13)

## Context

Voice recordings are personal data, and free hosted tiers may train on inputs.

## Decision

Default every speech role to self-hosted open-source models; a hosted provider is used only if its terms exclude training on our data (NFR-AI-7).

## Consequences

Zero cost and voice data stays on our servers. Revisit if accuracy on the golden set is not good enough.
