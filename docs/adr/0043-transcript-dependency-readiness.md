# ADR 0043: Resolve the Transcript story's session dependency

- Status: Accepted by owner after independent review of PR #165
- Date: 2026-10-20
- Sources: #57, #48, #118; docs/workflow.md Ready rule; SRS NFR-USE-1
- Refines: dependency readiness for #57 only

## Context

#57 depends on #48's session creation, plan ordering and progress implementation,
which is merged in main. #48 remains open because its NFR-USE-1 criterion requires
first-time-learner usability validation under #118. That study has not run. The
Ready rule says a story with an open blocker waits; the performance exception in
ADR 0039 does not cover usability. Independent review identified this ambiguity
and the owner requested its resolution.

## Decision

For #57 only, #48's merged implementation satisfies the implementation dependency.
The outstanding usability study does not block development completion or merge
of #57. #48 and #118 remain open, with their acceptance criteria unchanged and
NFR-USE-1 explicitly unverified. This decision neither closes #48 nor claims its
definition of done has been met.

This is a specific dependency disposition, not a general exception for open
blockers or a usability deferral under the performance policy. #57 must still
satisfy its functional, security, integration, coverage, independent review and
current-head CI gates. Its actual-server NFR-PERF-4 measurement remains deferred
until staging and unverified under #155, with the original target unchanged.

## Evidence and consequences

The #48 issue audit identifies implemented tests for plan lengths/order, progress,
starting another plan on library content, keyboard use and 360 px layout. The
independent review of PR #165 at 2de662f against main a74e930 found no confirmed
PR-introduced correctness or security defect. Its focused backend run passed
92 tests, including session-dependent transcript gating and persisted entry
locking, correction/export isolation, migration and architecture checks. The full
web coverage run passed 326 tests and the Transcript Chromium test passed at
360 px. These functional results do not establish first-time-learner usability.

The #48 usability criterion must still be completed through #118's moderated
study. This decision does not change any product requirement, release criterion,
runtime code or database schema, and does not authorize merging automatically.
