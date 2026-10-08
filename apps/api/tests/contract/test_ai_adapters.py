"""Contract tests for the AI adapters (ADR 0028): each adapter returns its port's schema.

Speech adapters replay recorded engine output (recordings/*.json) through the whole
adapter, so CI needs neither the models nor the speech libraries. Every recording in the
folder is replayed; add one with scripts/record_ai_contract.py.
"""

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from listenup.ai.config import ProviderEntry
from listenup.ai.ports import (
    Alignment,
    AlignmentPort,
    SpeechAssessment,
    SpeechAssessmentPort,
    TextAIPort,
    TextGeneration,
    TextTask,
    Transcript,
    TranscriptionPort,
)
from listenup.ai.providers import fake
from listenup.ai.providers.faster_whisper import FasterWhisperTranscription, RawTranscription
from listenup.ai.providers.wav2vec2_ctc import (
    RawAlignment,
    Wav2Vec2CtcAlignment,
    settings_label,
)

RECORDINGS = Path(__file__).parent / "recordings"


def recordings(port: str) -> list[dict[str, Any]]:
    found = [json.loads(p.read_text()) for p in sorted(RECORDINGS.glob("*.json"))]
    return [r for r in found if r["port"] == port]


class ReplayWhisper:
    def __init__(self, record: dict[str, Any]) -> None:
        self.version: str = record["version"]
        self._raw = RawTranscription.model_validate(record["raw"])
        self.runs = 0

    def run(self, audio: Path, language: str) -> RawTranscription:
        self.runs += 1
        return self._raw


class ReplayCtc:
    def __init__(self, record: dict[str, Any]) -> None:
        self.version: str = record["version"]
        self._raw = RawAlignment.model_validate(record["raw"])
        self.words: list[str] = []

    def run(self, audio: Path, words: list[str]) -> RawAlignment:
        self.words = words
        return self._raw


def entry_for(record: dict[str, Any]) -> ProviderEntry:
    return ProviderEntry(provider=record["provider"], model=record["model"])


def assert_schema[M: BaseModel](result: BaseModel, schema: type[M]) -> None:
    assert type(result) is schema
    assert schema.model_validate(result.model_dump()) == result  # round-trips the schema


def test_there_are_recordings_for_both_speech_adapters() -> None:
    assert recordings("transcription")
    assert recordings("alignment")


@pytest.mark.anyio
@pytest.mark.parametrize("record", recordings("transcription"), ids=lambda r: r["provider"])
async def test_faster_whisper_returns_the_transcription_schema(record: dict[str, Any]) -> None:
    engines: list[ReplayWhisper] = []

    def factory(entry: ProviderEntry) -> ReplayWhisper:
        engines.append(ReplayWhisper(record))
        return engines[-1]

    adapter = FasterWhisperTranscription(entry_for(record), engine_factory=factory)
    assert isinstance(adapter, TranscriptionPort)

    first = await adapter.transcribe(Path(record["input"]["audio"]), record["input"]["language"])
    second = await adapter.transcribe(Path(record["input"]["audio"]))

    assert_schema(first, Transcript)
    assert first == second
    assert len(engines) == 1 and engines[0].runs == 2  # loaded once per process
    assert first.provenance.model_dump() == {
        "provider": record["provider"],
        "model": record["model"],
        "version": record["version"],
    }
    raw_words = [w for s in record["raw"]["segments"] for w in s["words"] if w["word"].strip()]
    assert [w.text for w in first.words] == [w["word"].strip() for w in raw_words]
    assert all(w.start <= w.end for w in first.words)


@pytest.mark.anyio
@pytest.mark.parametrize("record", recordings("alignment"), ids=lambda r: r["provider"])
async def test_wav2vec2_returns_the_alignment_schema(record: dict[str, Any]) -> None:
    engine = ReplayCtc(record)
    adapter = Wav2Vec2CtcAlignment(entry_for(record), engine_factory=lambda _: engine)
    assert isinstance(adapter, AlignmentPort)

    text = record["input"]["text"]
    result = await adapter.align(Path(record["input"]["audio"]), text)

    assert_schema(result, Alignment)
    assert result.provenance.version == record["version"]
    options = record["options"]
    settings = settings_label(float(options.get("window_seconds", 0)), bool(options.get("int8")))
    assert record["version"].endswith(f"; {settings}")  # the settings are in the provenance
    assert len(result.words) == len(record["raw"]["spans"])
    reference = text.split()
    for word in result.words:
        assert word.text == reference[word.index]
        assert word.start <= word.end
        assert [u.label for u in word.units] == list(engine.words[result.words.index(word)])
    starts = [w.start for w in result.words]
    assert starts == sorted(starts)


def test_speech_libraries_are_not_imported_by_the_adapters_until_a_model_loads() -> None:
    for name in ("faster_whisper", "torch", "torchaudio"):
        assert name not in sys.modules


class Gist(BaseModel):
    summary: str = ""
    score: int = 0


@pytest.mark.anyio
async def test_fake_providers_return_their_ports_schemas(tmp_path: Path) -> None:
    def entry(model: str) -> ProviderEntry:
        return ProviderEntry(provider="fake", model=model)

    audio = tmp_path / "clip.mp4"
    transcriber = fake.FakeTranscription(entry("t"))
    aligner = fake.FakeAlignment(entry("a"))
    assessor = fake.FakeSpeechAssessment(entry("s"))
    text_ai = fake.FakeTextAI(entry("x"))
    assert isinstance(transcriber, TranscriptionPort)
    assert isinstance(aligner, AlignmentPort)
    assert isinstance(assessor, SpeechAssessmentPort)
    assert isinstance(text_ai, TextAIPort)

    assert_schema(await transcriber.transcribe(audio), Transcript)
    assert_schema(await aligner.align(audio, "hello there"), Alignment)
    assert_schema(await assessor.assess(audio, "hello there", audio), SpeechAssessment)
    fake.register_text_response("gist", {"summary": "a fox jumps", "score": 3})
    try:
        generated = await text_ai.generate(TextTask("gist", "v1"), {"gist": "fox"}, Gist)
    finally:
        fake.clear_text_responses()
    assert_schema(generated, TextGeneration[Gist])
    assert generated.value == Gist(summary="a fox jumps", score=3)
    assert generated.provenance.provider == "fake"
