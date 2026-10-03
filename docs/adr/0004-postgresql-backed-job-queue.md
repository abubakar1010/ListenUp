# ADR 0004: PostgreSQL-backed job queue

- Status: Accepted
- Date: 2026-10-03
- Source: [Software Architecture, section 13.1](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13)

## Context

Slow work (download, transcription, grading) must run outside requests, and the MVP must run at zero cost with few moving parts.

## Decision

Use Procrastinate on PostgreSQL with four lanes: speech-interactive, intake, ai, background (System Design 4). Jobs are enqueued in the same transaction as the data that triggers them.

## Consequences

No Redis to run or pay for, and no lost or orphaned jobs. Revisit when job volume exceeds what the database handles comfortably.
