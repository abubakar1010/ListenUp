"""Transcript public boundary: queue work; authorize before privileged cache reads."""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.content import service as content
from listenup.modules.practice import service as practice
from listenup.modules.transcript import repository
from listenup.modules.transcript.domain.sentences import ends_sentence
from listenup.modules.transcript.domain.spans import missing_spans
from listenup.platform.database import Database
from listenup.platform.errors import ProblemError
from listenup.platform.jobs import enqueue


@dataclass(frozen=True)
class PassageTranscript:
    words: list[str]
    start_ms: list[int]
    end_ms: list[int]
    confidence: list[int]
    sentence_starts: list[int]
    # Preserve provenance for every contributing cache row, never invent a merged provider.
    provenance: list[dict[str, str]]


async def queue_passage(db: AsyncSession, session: practice.PracticeSession) -> None:
    from listenup.modules.transcript.jobs import TRANSCRIBE

    item = await content.get_content(db, session.user_id, session.content_id)
    await enqueue(
        db,
        TRANSCRIBE,
        unique_key=f"transcript:{session.id}",
        lock=f"transcript-media:{item.media_object_id}",
        session_id=str(session.id),
        user_id=str(session.user_id),
    )


async def read_passage(
    db: AsyncSession, worker_database: Database, learner: uuid.UUID, session_id: uuid.UUID
) -> PassageTranscript:
    """Caller supplies its RLS request session and the worker-role read connection.

    No unrestricted read-by-media API is exposed. The step gate and explicit owner
    check precede opening the privileged transaction (FR-TX-5, NFR-SEC-2).
    """
    session = await practice.get_session(db, session_id)
    if session.user_id != learner:
        raise ProblemError(404, "session_not_found", "There is no such session.")
    await practice.require_reached(db, session_id, practice.Step.TRANSCRIPT)
    item = await content.get_content(db, learner, session.content_id)
    span = (session.passage.start_ms, session.passage.end_ms)
    async with worker_database.transaction() as worker:
        rows = await repository.overlapping(worker, item.media_object_id, span)
        gaps = missing_spans(span, [r.bounds for r in rows])
        failed = False
        for gap in gaps:
            if await repository.failed(worker, item.media_object_id, gap):
                failed = True
                break
    if gaps:
        if failed:
            raise ProblemError(409, "transcript_failed", "Transcription failed. Try again later.")
        raise ProblemError(409, "transcript_not_ready", "The passage transcript is not ready yet.")
    words: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    confidence: list[int] = []
    sentences: list[int] = []
    provenance: list[dict[str, str]] = []
    for row in rows:
        provenance.append({"origin": row.origin, **row.provider_info})
        for i, word in enumerate(row.words):
            if not span[0] <= row.start_ms[i] < span[1]:
                continue
            # Index zero is implicit at the start of each independently cached span.
            # It starts a new sentence here only if the preceding span ended one.
            if not words or (i in row.sentence_starts and (i > 0 or ends_sentence(words[-1]))):
                sentences.append(len(words))
            words.append(word)
            starts.append(row.start_ms[i])
            ends.append(min(row.end_ms[i], span[1]))
            confidence.append(row.confidence[i])
    return PassageTranscript(words, starts, ends, confidence, sentences, provenance)
