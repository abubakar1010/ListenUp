"""Scoring a submitted Dictation once the passage transcript is ready (#54, ADR 0041).

FR-DI-5, FR-TX-5. The job reads the cached passage words, scores with the pure
`score_dictation` and stores the diff; it is queued at submission and again when
`transcript.ready` is announced, so it is safe to run twice (the score is one
conditional update). A submission whose transcript is not ready stays
`waiting_transcript`: the job returns and the ready hook queues it again.
"""

import uuid

from listenup.modules.dictation import service
from listenup.modules.identity import service as identity
from listenup.modules.transcript import service as transcript
from listenup.platform.errors import ProblemError
from listenup.platform.jobs import JobDeps, Lane, job

SCORE_ATTEMPT = "dictation.score_attempt"

_NOT_USABLE = {"transcript_not_ready", "transcript_failed"}


@job(Lane.SPEECH_INTERACTIVE, SCORE_ATTEMPT)
async def score_attempt(deps: JobDeps, attempt_id: str, user_id: str) -> None:
    learner, attempt = uuid.UUID(user_id), uuid.UUID(attempt_id)
    async with deps.database.transaction(learner) as db:
        if not await identity.account_is_active(db, learner):
            return

        async def reference_for(
            session_id: uuid.UUID,
        ) -> tuple[list[str], list[int], list[int]] | None:
            try:
                passage = await transcript.reference_for_scoring(
                    db, deps.database, learner, session_id
                )
            except ProblemError as error:
                if error.code in _NOT_USABLE:
                    return None
                raise
            return passage.words, passage.start_ms, passage.end_ms

        await service.score_submission(db, learner, attempt, reference_for)


# Score a waiting submission when the transcript job announces the words (FR-TX-5).
transcript.on_passage_ready(service.on_transcript_ready)
