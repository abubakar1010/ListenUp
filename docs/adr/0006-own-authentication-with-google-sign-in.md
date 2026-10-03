# ADR 0006: Own authentication with Google sign-in

- Status: Accepted
- Date: 2026-10-03
- Source: [Software Architecture, section 13.1](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13)

## Context

Accounts are required (cross-browser progress). Hosted auth services add per-user fees and lock-in.

## Decision

Implement auth in the API: Argon2id password hashes, server sessions in httpOnly cookies, Google sign-in via OpenID Connect (in the MVP, decision D6). After 5 failed sign-ins an account's sign-in is locked for 15 minutes (D17).

## Consequences

No per-user fees and accounts stay in our database. Revisit if enterprise sign-in or compliance needs appear.
