# ADR 0021: Session state machine, entry changes and refusal codes

- Status: Accepted
- Date: 2026-10-03
- Source: issue #47; [SRS FR-PL-1 to FR-PL-7, SR-1 to SR-6](https://claude.ai/code/artifact/fd47a9cb-6515-4fde-a232-3ab8cc14f0dd); [Database Design 5, 8](https://claude.ai/code/artifact/ba05f7b3-f881-41e5-86d6-dcb94a509644); [Software Architecture 4.3, 5.2](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13)

## Context

Step order is the product's core rule and must live in one place (NFR-MNT-2). The SRS says the entry choice may change "until the Transcript step starts" and that a change adds or removes an entry exercise, but it does not say what "starts" means, or what happens to an entry exercise the learner already finished. The design names only `step_locked` and `entry_locked` as refusal codes. Its `session_steps_order` trigger fires only on UPDATE, and its passage CHECK compares `upper() - lower()`, which is NULL for an empty or unbounded range.

## Decision

- The state machine is the pure `Plan` in `modules/practice/domain/plan.py`. Other modules reach it only through `modules/practice/service.py`: `require_step` before a mode acts, `complete_step` when it is done, `require_reached` for data that is readable from a step on (FR-TX-5), plus `skip_step`, `change_entry`, `start_session` and `get_session`.
- Finishing a step opens the next one at once. The entry is locked when Transcript **opens** (the Database Design's reading of FR-PL-5), and `entry_locked_at` records when.
- A change of entry rebuilds the unfinished steps. A finished entry exercise stays in the plan and keeps its place, so the new path must start with it; otherwise the change is refused with `entry_locked`. Choosing the current entry again changes nothing.
- Refusals and their codes: 409 `step_locked` (with `step` and `open_step`), 409 `entry_locked`, 409 `step_not_skippable` (Blind, Dictation, Transcript), 422 `confirmation_required` (a skip without `confirmed`), 409 `step_not_in_plan`, 409 `session_closed` (completed or abandoned), 409 `session_changed` (the `version` check failed), 404 `session_not_found` and 404 `content_not_found`.
- Writes use optimistic concurrency: the session row is updated only where `version` still matches the snapshot, and the step rows are written after it, in position order.
- The database also refuses: `session_steps_order` fires on INSERT as well as UPDATE, because a rebuilt plan inserts its steps; and `sessions_passage_bounded` refuses empty, unbounded and negative passages.

## Consequences

Mode stories call `require_step` and `complete_step` and never write step rows themselves. A client that gets `session_changed` reloads the session and retries. The session endpoints (#48, #49) map the service's `ProblemError`s directly. A completed session still answers `require_reached`, so its transcript stays readable.
