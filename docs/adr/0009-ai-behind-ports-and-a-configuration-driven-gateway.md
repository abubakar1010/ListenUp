# ADR 0009: AI behind ports and a configuration-driven gateway

- Status: Accepted
- Date: 2026-10-03
- Source: [Software Architecture, section 13.1](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13)

## Context

The MVP must use free AI tiers, which change often, and must never be locked to one vendor.

## Decision

All AI goes through four provider-neutral ports (transcription, alignment, speech assessment, text AI) and one gateway that adds eligibility checks, quotas, fallbacks and output validation. Providers are chosen by configuration; prompts and schemas are versioned in our repository.

## Consequences

Switching provider is a configuration change gated by the golden-set regression run (NFR-AI-6).
