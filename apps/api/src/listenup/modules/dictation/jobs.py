"""Scoring a submitted Dictation once the passage transcript is ready (#54, ADR 0042).

FR-DI-5, FR-TX-5. The job reads the cached passage words, scores with the pure
`score_dictation` and stores the diff; it is queued at submission and again when
`transcript.ready` is announced, so it is safe to run twice (the score is one
conditional update). A submission whose transcript is not ready stays
`waiting_transcript`: the job returns and the ready hook queues it again. A transcript
that failed makes it `scoring_unavailable` at once, so the screen can say so (grading
never blocks the learner); a later successful transcription scores it after all.

The job is a pure-Python diff and a few queries, not speech inference, so it runs on the
`ai` lane (eight concurrent async jobs on the default pool) instead of taking one of the
two media slots that transcription and Shadow analysis need.
"""

import uuid

from listenup.modules.dictation import service
from listenup.modules.dictation.service import SCORE_ATTEMPT
from listenup.modules.identity import service as identity
from listenup.modules.transcript import service as transcript
from listenup.platform.errors import ProblemError
from listenup.platform.jobs import JobDeps, Lane, job

__all__ = ["SCORE_ATTEMPT", "score_attempt"]


@job(Lane.AI, SCORE_ATTEMPT)
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
                if error.code == "transcript_not_ready":
                    return None
                if error.code == "transcript_failed":
                    raise service.TranscriptUnavailable from error
                if error.status == 404:
                    return None  # the session or clip is gone: nothing to score, no retry helps
                raise
            return passage.words, passage.start_ms, passage.end_ms

        await service.score_submission(db, learner, attempt, reference_for)


# Continue a waiting submission when the transcript job announces the words (FR-TX-5), and
# tell it when transcription gave up. Registered on import; `listenup.worker.JOB_MODULES`
# imports this module in every pool, and a test pins that.
transcript.on_passage_ready(service.on_transcript_ready)
transcript.on_passage_failed(service.on_transcript_failed)
