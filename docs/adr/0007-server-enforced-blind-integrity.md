# ADR 0007: Server-enforced Blind integrity

- Status: Accepted
- Date: 2026-10-03
- Source: [Software Architecture, section 13.1](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13)

## Context

Blind requires listening without pause, seek or rewind. Client-only locks are trivially bypassed.

## Decision

The server issues an attempt-bound media URL and checks 5-second heartbeats (position advances with server time, page visible). Leaving, reloading or seeking voids the attempt. One automatic resume is allowed after an interruption the learner did not cause, 3 s after audio is ready, from 3 s before the stop (D13, D18).

## Consequences

Honest learners cannot slip and cheating is visible; recording the audio elsewhere cannot be prevented. Revisit if abuse patterns show the checks are too strict or too loose.
