"""The AI gateway: the one entry point callers use for every AI role (Architecture 7.2).

It reads the ordered provider list per role from `ai.yaml`, builds each adapter once per
process, and calls the first provider with a timeout, retrying timeouts and transient
errors with backoff. Anything else, or running out of attempts, raises `AIUnavailable`.

Not here yet (#64): eligibility checks (`trains_on_inputs`, NFR-AI-7), quotas and rate
limits (NFR-AI-8), output validation against value ranges beyond the port schema,
fallback to the next provider, and the `ai.calls` log.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from listenup.ai.config import AIConfig, ProviderEntry, load_config
from listenup.ai.errors import AIConfigError, AIUnavailable, TransientProviderError
from listenup.ai.ports import (
    Alignment,
    Preloadable,
    Role,
    SpeechAssessment,
    TextGeneration,
    TextTask,
    Transcript,
)
from listenup.ai.providers import fake
from listenup.ai.registry import DEFAULT_REGISTRY, Registry
from listenup.platform.config import get_settings

logger = logging.getLogger(__name__)

# Retried: the call may succeed if made again. ConnectionError and TimeoutError are
# subclasses of OSError; other OSErrors (a missing file) are not worth repeating.
RETRYABLE: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError, TransientProviderError)


class AIGateway:
    def __init__(
        self,
        config: AIConfig,
        *,
        environment: str = "local",
        registry: Registry = DEFAULT_REGISTRY,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._config = config
        self._registry = registry
        self._sleep = sleep
        self._adapters: dict[Role, object] = {}
        self._check(environment)

    def _factories(self, role: Role) -> Mapping[str, Callable[[ProviderEntry], object]]:
        factories: dict[Role, Mapping[str, Callable[[ProviderEntry], object]]] = {
            Role.TRANSCRIPTION: self._registry.transcription,
            Role.ALIGNMENT: self._registry.alignment,
            Role.SPEECH_ASSESSMENT: self._registry.speech_assessment,
            Role.TEXT_AI: self._registry.text_ai,
        }
        return factories[role]

    def _check(self, environment: str) -> None:
        for role in Role:
            known = self._factories(role)
            for entry in self._config.providers(role):
                if entry.provider not in known:
                    raise AIConfigError(
                        f"no {role.value} adapter named {entry.provider!r}; "
                        f"known: {', '.join(sorted(known))}"
                    )
                if entry.provider == fake.PROVIDER and environment == "production":
                    raise AIConfigError(
                        f"the fake {role.value} provider is not allowed in production"
                    )

    def entry(self, role: Role) -> ProviderEntry:
        """The provider the gateway calls for this role."""
        providers = self._config.providers(role)
        if not providers:
            raise AIUnavailable(role, "no provider configured")
        return providers[0]

    def _adapter(self, role: Role) -> tuple[ProviderEntry, Any]:
        entry = self.entry(role)
        if role not in self._adapters:
            self._adapters[role] = self._factories(role)[entry.provider](entry)
        return entry, self._adapters[role]

    async def _call[R](
        self, role: Role, entry: ProviderEntry, call: Callable[[], Awaitable[R]]
    ) -> R:
        attempts = entry.retries + 1
        last: BaseException | None = None
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                return await asyncio.wait_for(call(), entry.timeout_seconds)
            except RETRYABLE as exc:
                last = exc
                logger.warning(
                    "ai call failed",
                    extra={
                        "role": role.value,
                        "provider": entry.provider,
                        "attempt": attempt,
                        "elapsed_s": round(time.monotonic() - started, 3),
                        "error": type(exc).__name__,
                    },
                )
                if attempt < attempts:
                    await self._sleep(entry.retry_backoff_seconds * 2 ** (attempt - 1))
            except Exception as exc:
                raise AIUnavailable(role, f"{entry.provider} failed: {exc}") from exc
        raise AIUnavailable(role, f"{entry.provider} failed after {attempts} attempts") from last

    async def transcribe(self, audio: Path, language: str = "en") -> Transcript:
        entry, adapter = self._adapter(Role.TRANSCRIPTION)
        return await self._call(
            Role.TRANSCRIPTION, entry, lambda: adapter.transcribe(audio, language)
        )

    async def align(self, audio: Path, text: str) -> Alignment:
        entry, adapter = self._adapter(Role.ALIGNMENT)
        return await self._call(Role.ALIGNMENT, entry, lambda: adapter.align(audio, text))

    async def assess(
        self, recording: Path, reference_text: str, reference_audio: Path
    ) -> SpeechAssessment:
        entry, adapter = self._adapter(Role.SPEECH_ASSESSMENT)
        return await self._call(
            Role.SPEECH_ASSESSMENT,
            entry,
            lambda: adapter.assess(recording, reference_text, reference_audio),
        )

    async def generate[T: BaseModel](
        self, task: TextTask, input: Mapping[str, Any], output_schema: type[T]
    ) -> TextGeneration[T]:
        entry, adapter = self._adapter(Role.TEXT_AI)
        return await self._call(
            Role.TEXT_AI, entry, lambda: adapter.generate(task, input, output_schema)
        )

    async def preload(self, roles: tuple[Role, ...] = tuple(Role)) -> list[str]:
        """Load the models of providers marked `preload: true` among these roles, so the
        worker is ready only once they are in memory. Returns the providers loaded."""
        loaded = []
        for role in roles:
            providers = self._config.providers(role)
            if not providers or not providers[0].preload:
                continue
            entry, adapter = self._adapter(role)
            if isinstance(adapter, Preloadable):
                await asyncio.to_thread(adapter.load)
                loaded.append(f"{role.value}:{entry.provider}")
        return loaded


@lru_cache
def get_gateway() -> AIGateway:
    """The process-wide gateway, configured by `LISTENUP_AI_CONFIG` (default `ai.yaml`)."""
    settings = get_settings()
    path = Path(settings.ai_config) if settings.ai_config else None
    return AIGateway(load_config(path), environment=settings.environment)
