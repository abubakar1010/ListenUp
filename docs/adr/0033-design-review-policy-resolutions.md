# ADR 0033: Resolve the design review policies for Blind, intake, autosave and restoration

- Status: Accepted
- Date: 2026-10-09
- Source: PR #137 review; the owner delegated the policy choices and authorized the fixes in the review session.
- Requirements: FR-BL-3, SR-5, FR-CI-3, NFR-PERF-3, DR-1; UX-17, UX-34, UX-36.
- Refines: [ADR 0024](0024-blind-heartbeats-resume-and-attempt-bound-media.md), [ADR 0025](0025-dictation-drafts-autosave-and-passage-player.md); confirms [ADR 0027](0027-intake-admission-progress-and-refusals.md).

## Context

The exported design and accepted implementation ADRs disagree on Blind navigation and whole-clip access, the daily intake allowance, autosave durability and restoration. The owner asked the reviewer to choose the best options and apply them. These are explicit policy refinements, not claims that the original requirement meanings were unchanged.

## Decision

- **Warn before in-app navigation during an unfinished Blind listen, including Browser Back.** Use the leave confirmation with Stay as the safe action. Cancel keeps the listen running; confirming leaves and voids it. Do not pause playback while the confirmation is open. External tab close, hiding and reload still void an unfinished listen; browsers cannot guarantee a custom warning for those events.
- **Preserve a completed listen on leaving or reloading the gist form.** Completion must be recognized by the server, not just the client. This protects a listen already earned without permitting interruption during playback. This does not claim that unsent gist text already has persistent draft storage.
- **Refuse whole-clip playback for the same learner and media while any unfinished Blind listen is active.** Apply the ownership check first. The attempt-bound media route remains available; whole-clip access returns after server-recognized listen completion or voiding. An already-issued storage URL remains valid until expiry, so this reduces casual bypass rather than guaranteeing revocation. This supersedes ADR 0024's decision to leave the route unrestricted.
- **Confirm ADR 0027's admission rule.** Count at most 15 minutes per playable clip, reserve 15 minutes per pending clip, admit while count plus reservations is below 120 minutes, and admit the crossing clip whole. Reset at midnight UTC and display the server reset in local time. Reject based on server admission, not browser-reported duration or whether the file fits the minutes left. UX-36 and the required visual inventory must follow this rule.
- **The one-second autosave target means local durability.** A mark or text edit gets a durable local copy within one second (immediately for Dictation). When connected, start server synchronization after a two-second debounce following the last edit, with version checks and reconnect retries. Local saving is not a claim of cross-device synchronization or protection against cleared browser storage.
- **Restoration requires an explicit action during the seven-day grace period.** Sign-in offers Restore and Keep it deleted; it does not reactivate the account or unlock practice. Restore checks status and deadline atomically before clearing the schedule; Keep it deleted signs out and leaves the schedule intact. This preserves UX-34's protection against accidental restoration.
- **Correct the heartbeat summary.** A gap over 15 seconds without an eligible reported interruption voids the listen. A reported first network interruption is judged before that timeout and can receive the one resume, as the existing pure judge and its tests require.

## Consequences

The design documents and shared instructions record these policies without adding or renumbering requirement IDs. This documentation PR does not implement the new Back confirmation, whole-clip guard or explicit restoration flow. Follow-up implementation must test those behaviors, including other tabs, cancellation, ownership checks and races against the deletion deadline. Local durability for marks also needs verification when its story is implemented.

The published Final UI canvas is not edited by this PR. It needs the revised intake states, Back warning and whole-clip restriction. The current UX export format also differs from ADR 0030 and needs a separate review; this decision does not settle export UX.

ADR 0029 from PR #126's unpushed deletion WIP was not found in the repository. Do not recreate it from the handoff or mark its implementation validated. This ADR records the newly authorized restoration policy; recovery of the original WIP and account-deletion implementation remain separate work.
