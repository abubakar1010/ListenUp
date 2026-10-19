"""Provider-neutral routing with eligibility, durable admission and validated fallback."""

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from listenup.ai.accounting import Accounting, Outcome, PostgresAccounting
from listenup.ai.config import AIConfig, ProviderEntry, load_config
from listenup.ai.errors import AIConfigError, AIUnavailable, TransientProviderError
from listenup.ai.policy import CallContext, eligible
from listenup.ai.ports import (
    AIResult,
    Alignment,
    Preloadable,
    Role,
    SpeechAssessment,
    TextGeneration,
    TextTask,
    Transcript,
    Usage,
)
from listenup.ai.providers import fake
from listenup.ai.registry import DEFAULT_REGISTRY, Registry
from listenup.ai.validation import (
    revalidate,
    validate_alignment,
    validate_assessment,
    validate_transcript,
)
from listenup.platform.config import get_settings
from listenup.platform.database import Database
from listenup.platform.telemetry import record_ai_call

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
        accounting: Accounting | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._accounting = accounting if accounting is not None else get_accounting()
        self._config = config
        self._registry = registry
        self._sleep = sleep
        self._adapters: dict[tuple[Role, str], Any] = {}
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
        quota_config: dict[str, object] = {}
        for role in Role:
            providers = self._config.providers(role)
            if len({e.provider for e in providers}) != len(providers):
                raise AIConfigError("duplicate provider in role")
            for e in providers:
                # NFR-AI-8: speech admission reserves audio, not tokens. Refuse
                # unsupported caps rather than admit calls with a zero budget.
                if role is not Role.TEXT_AI and any("tokens" in cap for cap in e.limits.values()):
                    raise AIConfigError("token quotas require text_ai")
                limits = (e.limits, e.grading_reserve)
                if e.provider in quota_config and quota_config[e.provider] != limits:
                    raise AIConfigError("conflicting limits for shared provider")
                quota_config[e.provider] = limits
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

        for names in self._config.tasks.values():
            known_names = {e.provider for e in self._config.providers(Role.TEXT_AI)}
            if len(set(names)) != len(names) or not set(names) <= known_names:
                raise AIConfigError("invalid task provider order")

    def entry(self, role: Role) -> ProviderEntry:
        """The provider the gateway calls for this role."""
        providers = self._config.providers(role)
        if not providers:
            raise AIUnavailable(role, "no provider configured")
        return providers[0]

    def _adapter(self, role: Role) -> tuple[ProviderEntry, Any]:
        entry = self.entry(role)
        key = (role, entry.model_dump_json())
        if key not in self._adapters:
            self._adapters[key] = self._factories(role)[entry.provider](entry)
        return entry, self._adapters[key]

    def text_input_budget(self, task: str) -> int:
        """Bytes of serialized input that every provider of this text task accepts, so
        callers can `fit` reference text before calling (ADR 0043). It is the admission
        rule of `_route` read back: the input limit less the prompt overhead, using the
        task's `task_budgets` when set, and the smallest value across the task's providers."""
        providers = self._config.providers(Role.TEXT_AI)
        if task in self._config.tasks:
            by_name = {entry.provider: entry for entry in providers}
            providers = tuple(by_name[name] for name in self._config.tasks[task])
        if not providers:
            raise AIUnavailable(Role.TEXT_AI, "no provider configured")
        caps = self._config.task_budgets.get(task)
        if caps is not None:
            return max(0, caps.input_tokens - caps.prompt_tokens)
        return max(0, min(e.input_token_limit - e.prompt_token_budget for e in providers))

    async def quota_saving(self) -> bool:
        """Grading owns templates; this signal also prevents rounds 1/2 AI calls."""
        if self._config.saving_mode:
            return True
        for entry in self._config.providers(Role.TEXT_AI):
            if await self._accounting.remaining(entry) <= 0.25:
                return True
        return False

    async def _dispatch[R: AIResult](
        self,
        role: Role,
        task: str,
        call: Callable[[Any], Awaitable[Any]],
        validate: Callable[[Any], R],
        context: CallContext | None = None,
        prompt: str | None = None,
        input_bytes: int = 0,
    ) -> R:
        context = context or CallContext()
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", task) or (
            prompt is not None and not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", prompt)
        ):
            raise AIUnavailable(role, "invalid task metadata")
        try:
            if task == "shadow_feedback" and context.round != 3 and await self.quota_saving():
                raise AIUnavailable(role, "template_feedback")
            return await self._route(role, task, call, validate, context, prompt, input_bytes)
        except AIUnavailable:
            raise
        except Exception:
            pass
        # Accounting outages must never result in unmetered provider calls or leak SQL.
        raise AIUnavailable(role, "accounting unavailable") from None

    async def _route[R: AIResult](
        self,
        role: Role,
        task: str,
        call: Callable[[Any], Awaitable[Any]],
        validate: Callable[[Any], R],
        context: CallContext,
        prompt: str | None,
        input_bytes: int,
    ) -> R:
        providers = self._config.providers(role)
        if role is Role.TEXT_AI and task in self._config.tasks:
            by_name = {entry.provider: entry for entry in providers}
            providers = tuple(by_name[name] for name in self._config.tasks[task])
        if not providers:
            raise AIUnavailable(role, "no provider configured")
        for fallback_depth, entry in enumerate(providers):
            if not eligible(entry, context, role):
                await self._accounting.skip(entry, role, task, prompt, "ineligible")
                continue
            if role is Role.TEXT_AI:
                if task in self._config.task_budgets:
                    caps = self._config.task_budgets[task]
                    entry = entry.model_copy(
                        update={
                            "input_token_limit": caps.input_tokens,
                            "output_token_limit": caps.output_tokens,
                            "prompt_token_budget": caps.prompt_tokens,
                        }
                    )
                if input_bytes + entry.prompt_token_budget > entry.input_token_limit:
                    await self._accounting.skip(entry, role, task, prompt, "quota")
                    continue
                budget = Usage(
                    input_tokens=entry.input_token_limit, output_tokens=entry.output_token_limit
                )
            else:
                if context.audio_seconds is None and any(
                    "audio_seconds" in limits for limits in entry.limits.values()
                ):
                    await self._accounting.skip(entry, role, task, prompt, "quota")
                    continue  # cannot admit metered audio without its duration
                budget = Usage(audio_seconds=context.audio_seconds or 0)
            key = (role, entry.model_dump_json())
            for attempt in range(entry.retries + 1):
                ticket = await self._accounting.admit(
                    entry,
                    role,
                    task,
                    prompt,
                    budget,
                    task not in ("extract_key_points", "grade_gist"),
                    fallback_depth=fallback_depth,
                    queue_delay_ms=int(context.queue_delay_seconds * 1000),
                )
                if ticket is None:
                    break
                started = time.monotonic()
                outcome: Outcome = "error"
                result = None
                retry = False
                trusted_version = None
                try:
                    if key not in self._adapters:
                        self._adapters[key] = self._factories(role)[entry.provider](entry)
                    resolver = self._registry.versions.get(entry.provider)
                    trusted_version = resolver(entry) if resolver is not None else None
                    raw = await asyncio.wait_for(call(self._adapters[key]), entry.timeout_seconds)
                    outcome = "invalid_output"
                    result = validate(raw)
                    if (
                        result.provenance.provider != entry.provider
                        or result.provenance.model != entry.model
                    ):
                        raise ValueError("provenance mismatch")
                    if (
                        isinstance(result, TextGeneration)
                        and len(result.value.model_dump_json().encode())
                        > entry.output_token_limit * 4
                    ):
                        raise ValueError("output budget exceeded")
                    if (
                        isinstance(result, Transcript)
                        and any("audio_seconds" in limits for limits in entry.limits.values())
                        and result.duration_seconds > budget.audio_seconds
                    ):
                        raise ValueError("transcript exceeds reserved audio budget")
                    if result.usage is not None:
                        if role is Role.TEXT_AI and (
                            result.usage.input_tokens > budget.input_tokens
                            or result.usage.output_tokens > budget.output_tokens
                        ):
                            raise ValueError("usage exceeds reserved token budget")
                        if (
                            any("audio_seconds" in limits for limits in entry.limits.values())
                            and result.usage.audio_seconds > budget.audio_seconds
                        ):
                            raise ValueError("usage exceeds reserved audio budget")
                    if not re.fullmatch(r"[A-Za-z0-9_.+;= :()-]{1,256}", result.provenance.version):
                        raise ValueError("unsafe version metadata")
                    if trusted_version is not None and result.provenance.version != trusted_version:
                        raise ValueError("version provenance mismatch")
                    outcome = "ok"
                except asyncio.CancelledError:
                    # A durable pending reservation remains charged if settlement fails.
                    with suppress(Exception):
                        await self._accounting.finish(
                            ticket,
                            "cancelled",
                            int((time.monotonic() - started) * 1000),
                            None,
                            None,
                        )
                    raise
                except RETRYABLE as error:
                    outcome = "timeout" if isinstance(error, TimeoutError) else "error"
                    retry = attempt < entry.retries
                except Exception:
                    result = None
                elapsed = time.monotonic() - started
                # Response metadata can contain learner content even when it matches
                # a character allowlist. Persist only registered deployment metadata.
                version = trusted_version if outcome == "ok" else None
                usage = result.usage if outcome == "ok" and result is not None else None
                if usage is None and outcome == "ok" and isinstance(result, Transcript):
                    usage = Usage(audio_seconds=result.duration_seconds)
                await self._accounting.finish(ticket, outcome, int(elapsed * 1000), version, usage)
                record_ai_call(entry.provider, task, elapsed, outcome == "ok")
                if outcome == "ok" and result is not None:
                    return result
                if retry:
                    await self._sleep(entry.retry_backoff_seconds * 2**attempt)
                    continue
                break
        raise AIUnavailable(role, "no eligible provider produced a valid result") from None

    async def transcribe(
        self, audio: Path, language: str = "en", *, context: CallContext | None = None
    ) -> Transcript:
        return await self._dispatch(
            Role.TRANSCRIPTION,
            "transcribe",
            lambda a: a.transcribe(audio, language),
            lambda r: validate_transcript(r),
            context,
        )

    async def align(
        self, audio: Path, text: str, *, context: CallContext | None = None
    ) -> Alignment:
        return await self._dispatch(
            Role.ALIGNMENT,
            "align",
            lambda a: a.align(audio, text),
            lambda r: validate_alignment(r, text),
            context,
        )

    async def assess(
        self,
        recording: Path,
        reference_text: str,
        reference_audio: Path,
        *,
        context: CallContext | None = None,
    ) -> SpeechAssessment:
        return await self._dispatch(
            Role.SPEECH_ASSESSMENT,
            "assess",
            lambda a: a.assess(recording, reference_text, reference_audio),
            lambda r: validate_assessment(r, reference_text),
            context,
        )

    async def generate[T: BaseModel](
        self,
        task: TextTask,
        input: Mapping[str, Any],
        output_schema: type[T],
        *,
        context: CallContext | None = None,
    ) -> TextGeneration[T]:
        def validate(raw: Any) -> TextGeneration[T]:
            schema = cast(type[TextGeneration[T]], TextGeneration.__class_getitem__(output_schema))
            result = revalidate(schema, raw)
            if result.task != task.name or result.prompt_version != task.version:
                raise ValueError("task provenance mismatch")
            return result

        return await self._dispatch(
            Role.TEXT_AI,
            task.name,
            lambda a: a.generate(task, input, output_schema),
            validate,
            context,
            task.version,
            len(json.dumps(input, ensure_ascii=False).encode()),
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


def get_accounting() -> Accounting:
    return PostgresAccounting(Database(get_settings().database_url))


@lru_cache
def get_gateway() -> AIGateway:
    """The process-wide gateway, configured by `LISTENUP_AI_CONFIG` (default `ai.yaml`)."""
    settings = get_settings()
    path = Path(settings.ai_config) if settings.ai_config else None
    return AIGateway(load_config(path), environment=settings.environment)
