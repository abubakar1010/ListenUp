"""Transcript public boundary: queue work; authorize before privileged cache reads."""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.content import service as content
from listenup.modules.practice import service as practice
from listenup.modules.transcript import repository
from listenup.modules.transcript.domain.sentences import ends_sentence
from listenup.modules.transcript.domain.spans import missing_spans
from listenup.platform.database import Database
from listenup.platform.errors import ProblemError
from listenup.platform.export import ExportPart, learner_rows
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
    edited_word_indices: list[int] = field(default_factory=list)


ReadyHook = Callable[[AsyncSession, uuid.UUID, uuid.UUID], Awaitable[None]]
"""Called with (transaction, learner, session id) when a session's passage is ready."""

_ready_hooks: list[ReadyHook] = []
_failed_hooks: list[ReadyHook] = []


def on_passage_ready(hook: ReadyHook) -> None:
    """Register work that waits for the passage words, for example Dictation scoring.

    Modes register from their own `jobs.py`, so the transcript module imports no mode
    and `practice` never reaches one through it (import-linter, Architecture 4.3).
    """
    if hook not in _ready_hooks:
        _ready_hooks.append(hook)


def on_passage_failed(hook: ReadyHook) -> None:
    """Register work for a passage whose transcription gave up (like `on_passage_ready`)."""
    if hook not in _failed_hooks:
        _failed_hooks.append(hook)


async def announce_ready(db: AsyncSession, learner: uuid.UUID, session_id: uuid.UUID) -> None:
    """Run the ready hooks. The caller passes a transaction scoped to `learner` and separate
    from the one that published `transcript.ready`, so a failing hook is retried with the job
    and never takes the announcement with it."""
    for hook in _ready_hooks:
        await hook(db, learner, session_id)


async def announce_failed(db: AsyncSession, learner: uuid.UUID, session_id: uuid.UUID) -> None:
    """Run the failure hooks, in a learner-scoped transaction like `announce_ready`."""
    for hook in _failed_hooks:
        await hook(db, learner, session_id)


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
    return await _read(
        db, worker_database, learner, session_id, practice.Step.TRANSCRIPT, apply_corrections=True
    )


async def reference_for_scoring(
    db: AsyncSession, worker_database: Database, learner: uuid.UUID, session_id: uuid.UUID
) -> PassageTranscript:
    """The passage words for scoring a Dictation submission (FR-DI-5, FR-TX-5).

    Only the Dictation scoring job calls it. Dictation hides the transcript, so the
    words go into the stored diff and never into a response before submission; the gate
    is that the learner has reached Dictation rather than Transcript. The seam where
    the learner's own corrections will apply (#56) is the caller, `dictation.service`.
    """
    return await _read(db, worker_database, learner, session_id, practice.Step.DICTATION)


async def _read(
    db: AsyncSession,
    worker_database: Database,
    learner: uuid.UUID,
    session_id: uuid.UUID,
    reached: practice.Step,
    *,
    apply_corrections: bool = False,
) -> PassageTranscript:
    session = await practice.get_session(db, session_id)
    if session.user_id != learner:
        raise ProblemError(404, "session_not_found", "There is no such session.")
    await practice.require_reached(db, session_id, reached)
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
    overlays = (
        await repository.corrections(db, learner, [row.id for row in rows])
        if apply_corrections
        else {}
    )
    words: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    confidence: list[int] = []
    sentences: list[int] = []
    provenance: list[dict[str, str]] = []
    edited: list[int] = []
    previous_reference = ""
    for row in rows:
        provenance.append({"origin": row.origin, **row.provider_info})
        for i, word in enumerate(row.words):
            if not span[0] <= row.start_ms[i] < span[1]:
                continue
            # Index zero is implicit at the start of each independently cached span.
            # It starts a new sentence here only if the preceding span ended one.
            if not words or (
                i in row.sentence_starts and (i > 0 or ends_sentence(previous_reference))
            ):
                sentences.append(len(words))
            identity = (row.id, i)
            if identity in overlays:
                edited.append(len(words))
            words.append(overlays.get(identity, word))
            previous_reference = word
            starts.append(row.start_ms[i])
            ends.append(min(row.end_ms[i], span[1]))
            confidence.append(row.confidence[i])
    return PassageTranscript(words, starts, ends, confidence, sentences, provenance, edited)


async def export_data(db: AsyncSession, learner: uuid.UUID) -> ExportPart:
    return ExportPart(tables=(await learner_rows(db, "content.transcript_corrections", learner),))
