"""Which adapter implements which provider name for each role (ADR 0028).

A provider name in `ai.yaml` must appear here for its role. Adding a provider means one
adapter file in `ai/providers/` and one line here; no caller changes (NFR-AI-2).
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from listenup.ai.config import ProviderEntry
from listenup.ai.ports import AlignmentPort, SpeechAssessmentPort, TextAIPort, TranscriptionPort
from listenup.ai.providers import fake, fake_assessment
from listenup.ai.providers.faster_whisper import FasterWhisperTranscription
from listenup.ai.providers.faster_whisper import version_for as whisper_version
from listenup.ai.providers.openai_compatible import OpenAICompatibleTextAI
from listenup.ai.providers.openai_compatible import version_for as text_version
from listenup.ai.providers.wav2vec2_ctc import Wav2Vec2CtcAlignment
from listenup.ai.providers.wav2vec2_ctc import version_for as alignment_version

# One adapter, several provider ids: each id keeps its own quota counters (ADR 0041), and
# `openai-compatible` serves any other llama.cpp or vLLM server (ADR 0046).
OPENAI_COMPATIBLE = ("groq", "ollama", "openai-compatible")


@dataclass(frozen=True)
class Registry:
    # Trusted code/configuration only: never derive these from an inference response.
    # Unregistered versions stay NULL in operational logs, not response-supplied prose.
    versions: dict[str, Callable[[ProviderEntry], str]] = field(default_factory=dict)
    transcription: dict[str, Callable[[ProviderEntry], TranscriptionPort]] = field(
        default_factory=dict
    )
    alignment: dict[str, Callable[[ProviderEntry], AlignmentPort]] = field(default_factory=dict)
    speech_assessment: dict[str, Callable[[ProviderEntry], SpeechAssessmentPort]] = field(
        default_factory=dict
    )
    text_ai: dict[str, Callable[[ProviderEntry], TextAIPort]] = field(default_factory=dict)


DEFAULT_REGISTRY = Registry(
    versions={
        fake.PROVIDER: lambda _: fake.VERSION,
        fake_assessment.PROVIDER: lambda _: fake_assessment.VERSION,
        "faster-whisper": whisper_version,
        "wav2vec2-ctc": alignment_version,
        **dict.fromkeys(OPENAI_COMPATIBLE, text_version),
    },
    transcription={
        fake.PROVIDER: fake.FakeTranscription,
        "faster-whisper": FasterWhisperTranscription,
    },
    alignment={
        fake.PROVIDER: fake.FakeAlignment,
        "wav2vec2-ctc": Wav2Vec2CtcAlignment,
    },
    speech_assessment={
        fake.PROVIDER: fake.FakeSpeechAssessment,
        fake_assessment.PROVIDER: fake_assessment.FakeAssessment,
    },
    text_ai={
        fake.PROVIDER: fake.FakeTextAI,
        **dict.fromkeys(OPENAI_COMPATIBLE, OpenAICompatibleTextAI),
    },
)
