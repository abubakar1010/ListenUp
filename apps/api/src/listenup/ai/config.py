"""The AI configuration file, `ai.yaml` (Architecture 7.2, NFR-AI-2, ADR 0028).

Each role has an ordered fallback list; text tasks may override its order (ADR 0041).
The packaged `ai.yaml` is
the default for every environment; `LISTENUP_AI_CONFIG` points at another file, such as
the packaged `ai.fake.yaml` for tests and local runs without speech models.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from listenup.ai.errors import AIConfigError
from listenup.ai.ports import Role

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = PACKAGE_DIR / "ai.yaml"
FAKE_CONFIG = PACKAGE_DIR / "ai.fake.yaml"

OptionValue = str | int | float | bool


class ProviderEntry(BaseModel):
    """One provider in a role's list."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(min_length=1)  # adapter key, e.g. "faster-whisper" or "fake"
    model: str = Field(default="default", min_length=1)
    timeout_seconds: float = Field(default=60.0, gt=0, allow_inf_nan=False)
    retries: int = Field(default=1, ge=0, le=5)  # extra attempts after the first
    retry_backoff_seconds: float = Field(
        default=1.0, ge=0, allow_inf_nan=False
    )  # doubled on each retry
    preload: bool = False  # load the model when the worker starts (System Design 5.2)
    # Unknown eligibility is denied, including unverified hosted controls (ADR 0037).
    trains_on_inputs: bool | None = None
    local: bool = False
    enabled: bool = True
    accepted: bool = False
    retention_verified: bool = False
    regions: tuple[str, ...] = ()
    populations: tuple[str, ...] = ()
    projected_input_cost_per_million: float = Field(default=0, ge=0, allow_inf_nan=False)
    projected_output_cost_per_million: float = Field(default=0, ge=0, allow_inf_nan=False)
    projected_audio_cost_per_hour: float = Field(default=0, ge=0, allow_inf_nan=False)
    limits: dict[
        Literal["minute", "day", "month"], dict[Literal["calls", "tokens", "audio_seconds"], float]
    ] = Field(default_factory=dict)
    grading_reserve: float = Field(default=0.25, ge=0, le=1)
    input_token_limit: int = Field(default=8192, gt=0)
    output_token_limit: int = Field(default=1024, gt=0)
    prompt_token_budget: int = Field(default=1024, ge=0)
    options: dict[str, OptionValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_limits(self) -> "ProviderEntry":
        import math

        if any(
            not math.isfinite(v) or v < 0
            for limits in self.limits.values()
            for v in limits.values()
        ):
            raise ValueError("quota limits must be finite and nonnegative")
        return self


class TokenBudget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    input_tokens: int = Field(gt=0)
    output_tokens: int = Field(gt=0)
    prompt_tokens: int = Field(ge=0)


class AIConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1]
    roles: dict[Role, tuple[ProviderEntry, ...]]

    tasks: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    saving_mode: bool = True
    task_budgets: dict[str, TokenBudget] = Field(default_factory=dict)

    def providers(self, role: Role) -> tuple[ProviderEntry, ...]:
        return self.roles.get(role, ())


def parse_config(text: str, source: str = "<string>") -> AIConfig:
    try:
        data = yaml.safe_load(text)
        return AIConfig.model_validate(data)
    except (yaml.YAMLError, ValidationError) as exc:
        raise AIConfigError(f"invalid AI configuration in {source}: {exc}") from exc


def load_config(path: Path | None = None) -> AIConfig:
    target = path or DEFAULT_CONFIG
    try:
        text = target.read_text()
    except OSError as exc:
        raise AIConfigError(f"cannot read AI configuration {target}: {exc}") from exc
    return parse_config(text, str(target))
