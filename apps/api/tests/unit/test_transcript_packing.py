"""Provider output becomes stable, absolute packed arrays."""

import pytest

from listenup.ai.ports import Provenance, TimedWord, Transcript, TranscriptSegment
from listenup.modules.transcript.packing import pack


def result():
    return Transcript(
        language="en",
        duration_seconds=10,
        provenance=Provenance(provider="test", model="speech", version="v1"),
        segments=(
            TranscriptSegment(
                start=1,
                end=2,
                text="Hello.",
                words=(TimedWord(text="Hello.", start=1.125, end=1.9, confidence=0.987),),
            ),
            TranscriptSegment(
                start=3,
                end=4,
                text="Again.",
                words=(TimedWord(text="Again.", start=3, end=4, confidence=0.8),),
            ),
        ),
    )


def test_absolute_word_offsets_and_sentence_boundaries():
    packed = pack(result(), (5000, 15000))
    assert packed.words == ["Hello.", "Again."]
    assert packed.start_ms == [6125, 8000]
    assert packed.end_ms == [6900, 9000]
    assert packed.confidence == [987, 800]
    assert packed.sentence_starts == [0, 1]
    assert packed.provider_info == {"provider": "test", "model": "speech", "version": "v1"}


def test_invalid_provider_timings_rejected():
    with pytest.raises(ValueError):
        pack(result(), (5000, 6000))


def test_silence_is_valid_cached_coverage():
    packed = pack(result().model_copy(update={"segments": ()}), (0, 10000))
    assert packed.words == packed.sentence_starts == []


def test_sentences_follow_punctuation_across_provider_segments():
    def word(text, start, end):
        return TimedWord(text=text, start=start, end=end, confidence=0.9)

    transcript = result().model_copy(
        update={
            "segments": (
                TranscriptSegment(start=0, end=1, text="A", words=(word("A", 0, 1),)),
                TranscriptSegment(
                    start=1,
                    end=4,
                    text="sentence. Next one?",
                    words=(word("sentence.", 1, 2), word("Next", 2, 3), word("one?", 3, 4)),
                ),
            )
        }
    )
    assert pack(transcript, (0, 10000)).sentence_starts == [0, 2]


def test_empty_word_timing_is_rejected():
    word = TimedWord(text="empty", start=1, end=1, confidence=0.9)
    transcript = result().model_copy(
        update={"segments": (TranscriptSegment(start=1, end=1, text="empty", words=(word,)),)}
    )
    with pytest.raises(ValueError, match="empty"):
        pack(transcript, (0, 10000))


@pytest.mark.parametrize("title", ["Dr.", "Mr.", "Mrs.", "Ms.", "Prof.", "Rev."])
def test_person_titles_do_not_end_sentences(title):
    transcript = result().model_copy(
        update={
            "segments": (
                TranscriptSegment(
                    start=0,
                    end=2,
                    text="",
                    words=tuple(
                        TimedWord(text=word, start=i * 0.3, end=i * 0.3 + 0.2, confidence=0.9)
                        for i, word in enumerate([title, "Jones", "arrived.", "Next."])
                    ),
                ),
            )
        }
    )
    assert pack(transcript, (0, 10000)).sentence_starts == [0, 3]
