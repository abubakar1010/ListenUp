"""The Transcript experience composes public module services, never cache queries."""

import uuid
from itertools import pairwise

from sqlalchemy.ext.asyncio import AsyncSession

from listenup.modules.content import service as content
from listenup.modules.practice import service as practice
from listenup.modules.review import schemas
from listenup.modules.transcript import service as transcript
from listenup.platform.database import Database


async def read_transcript(
    db: AsyncSession, worker_database: Database, learner: uuid.UUID, session_id: uuid.UUID
) -> schemas.TranscriptReview:
    # FR-TX-5: this boundary authorizes ownership and step before privileged reads.
    # read_passage applies the learner's overlay using cache-row/local-word identity.
    # Review never queries corrections or changes the shared reference (#57).
    passage = await transcript.read_passage(db, worker_database, learner, session_id)
    session = await practice.get_session(db, session_id)
    item = await content.get_content(db, learner, session.content_id)
    edited = set(passage.edited_word_indices)
    words = [
        schemas.TranscriptWord(
            index=i,
            text=word,
            start_ms=start,
            end_ms=end,
            edited=i in edited,
        )
        for i, (word, start, end) in enumerate(
            zip(passage.words, passage.start_ms, passage.end_ms, strict=True)
        )
    ]
    boundaries = [*passage.sentence_starts, len(words)]
    lines = []
    for i, (left, right) in enumerate(pairwise(boundaries)):
        sentence = words[left:right]
        lines.append(
            schemas.TranscriptLine(
                index=i,
                start_ms=sentence[0].start_ms,
                end_ms=max(word.end_ms for word in sentence),
                words=sentence,
            )
        )
    return schemas.TranscriptReview(
        session_id=session_id,
        passage=schemas.TranscriptPassage(
            start_ms=session.passage.start_ms, end_ms=session.passage.end_ms
        ),
        media_url=f"/api/v1/media/{item.media_object_id}",
        lines=lines,
    )
