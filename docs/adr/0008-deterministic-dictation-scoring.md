# ADR 0008: Deterministic Dictation scoring

- Status: Accepted
- Date: 2026-10-03
- Source: [Software Architecture, section 13.1](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13)

## Context

Dictation feedback must be explainable, free and testable.

## Decision

Score Dictation with a pure function: normalise both texts, align words by weighted edit distance, and classify each reference word as correct, spelling slip, wrong or missing. No AI.

## Consequences

Explainable results, zero cost, property-based tests.
