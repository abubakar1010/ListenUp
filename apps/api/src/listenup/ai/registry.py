"""Which adapter implements which provider name for each role (ADR 0028).

A provider name in `ai.yaml` must appear here for its role. Adding a provider means one
adapter file in `ai/providers/` and one line here; no caller changes (NFR-AI-2).
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from listenup.ai.config import ProviderEntry
from listenup.ai.ports import AlignmentPort, SpeechAssessmentPort, TextAIPort, TranscriptionPort
from listenup.ai.providers import fake
from listenup.ai.providers.faster_whisper import FasterWhisperTranscription
from listenup.ai.providers.wav2vec2_ctc import Wav2Vec2CtcAlignment


@dataclass(frozen=True)
class Registry:
    transcription: dict[str, Callable[[ProviderEntry], TranscriptionPort]] = field(
        default_factory=dict
    )
    alignment: dict[str, Callable[[ProviderEntry], AlignmentPort]] = field(default_factory=dict)
    speech_assessment: dict[str, Callable[[ProviderEntry], SpeechAssessmentPort]] = field(
        default_factory=dict
    )
    text_ai: dict[str, Callable[[ProviderEntry], TextAIPort]] = field(default_factory=dict)


DEFAULT_REGISTRY = Registry(
    transcription={
        fake.PROVIDER: fake.FakeTranscription,
        "faster-whisper": FasterWhisperTranscription,
    },
    alignment={
        fake.PROVIDER: fake.FakeAlignment,
        "wav2vec2-ctc": Wav2Vec2CtcAlignment,
    },
    speech_assessment={fake.PROVIDER: fake.FakeSpeechAssessment},
    text_ai={fake.PROVIDER: fake.FakeTextAI},
)
