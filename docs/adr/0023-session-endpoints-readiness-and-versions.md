# ADR 0023: Plans start only on playable clips, and session writes carry the version

- Status: Accepted; the typed passage is superseded by the waveform picker of ADR 0026
- Date: 2026-10-03
- Source: issues #48 and #49; [SRS FR-PL-1 to FR-PL-7, FR-LB-2, C2](https://claude.ai/code/artifact/fd47a9cb-6515-4fde-a232-3ab8cc14f0dd); [Software Architecture 9.2 (Sessions)](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13); final UI screens B04, C01, C02 and G04

## Context

The session endpoints (#48, #49) sit on the practice service of ADR 0021. Its `start_session` checks only that the learner owns the content item. Three questions were open: whether a plan may start while the clip is still being prepared, how a passage is chosen before the waveform picker (#42) exists, and how a client's view of a session is kept from overwriting a newer one.

## Decision

- **A plan starts only on a playable clip.** Blind and Dictation, the first step of every plan, need playback, so `practice.service.start_plan` refuses any other media status with 409 `content_not_ready` and the clip's `content_status`. The alternative, starting the plan and holding the first step until the clip is ready, would leave sessions on clips that fail and never play. The web page says the clip is still being prepared and offers no Start button.
- **The passage is checked twice.** The service refuses a passage that is not 30 s to 15 min long (422 `invalid_passage`, C2), a clip under 30 s (422 `clip_too_short`), and a passage that ends after the clip once its duration is known (422 `passage_outside_clip`). Status and duration come from `content.service.get_content`, so practice never reads content tables. The web client checks the same rules as the learner types.
- **Until #42, the passage is typed.** The default is the whole clip when it is 30 s to 15 min long, otherwise its first 15 minutes; a part is typed as start and end in mm:ss. The design's default of 2:30 from the first speech needs the transcript and the peaks, so it waits for #42.
- **Every write carries the version the client last saw.** `PATCH /sessions/{id}/entry` and `POST /sessions/{id}/steps/{step}/skip` take `version` in the body; `change_entry` and `skip_step` take it as `expected_version` and refuse a different one with 409 `session_changed` before any rule is checked. The service's own optimistic update still guards against a concurrent write between load and save. A skip needs `confirmed: true`, which defaults to false, so a client that forgets it gets 422 `confirmation_required`.
- **Creation is idempotent.** `POST /sessions` runs in `run_once`; the web client sends one `Idempotency-Key` per distinct request and reuses it on a retry.
- **The sessions list is ordered by activity.** `GET /sessions` pages by keyset on `(updated_at, id)`, newest first, on `sessions_user_idx`, so the plan the learner touched last comes first. A session that changes while the learner pages may move to the top and be seen twice or missed; the list is for finding a plan, not a ledger.

## Consequences

Content that is processing shows no "Start a plan" action in the library. When #42 adds the waveform picker it replaces the typed fields, and the server's checks stay as they are. A client that receives `session_changed` reloads the session and tries again; the web client does this on any refused write. When the content module gains a single-item endpoint, the web client's `useClip` should use it instead of searching the library pages.
