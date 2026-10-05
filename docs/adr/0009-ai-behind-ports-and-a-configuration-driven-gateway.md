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

## Implementation

The ports are the Protocols in `apps/api/src/listenup/ai/ports.py` (`TranscriptionPort`, `AlignmentPort`, `SpeechAssessmentPort`, `TextAIPort`), the providers per role are listed in `listenup/ai/ai.yaml`, and the entry point is `listenup/ai/gateway.py`. ADR 0028 records the first part (timeout and retry on the first provider, the self-hosted transcription and alignment adapters); eligibility, quotas, output validation, fallbacks and the call log follow in #64.
