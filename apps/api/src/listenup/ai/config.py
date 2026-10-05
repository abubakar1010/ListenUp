"""The AI configuration file, `ai.yaml` (Architecture 7.2, NFR-AI-2, ADR 0028).

Each role has an ordered list of providers. The gateway uses the first today; the
fallbacks after it are tried once the full gateway lands (#64). The packaged `ai.yaml` is
the default for every environment; `LISTENUP_AI_CONFIG` points at another file, such as
the packaged `ai.fake.yaml` for tests and local runs without speech models.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    timeout_seconds: float = Field(default=60.0, gt=0)
    retries: int = Field(default=1, ge=0, le=5)  # extra attempts after the first
    retry_backoff_seconds: float = Field(default=1.0, ge=0)  # doubled on each retry
    preload: bool = False  # load the model when the worker starts (System Design 5.2)
    options: dict[str, OptionValue] = Field(default_factory=dict)


class AIConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1]
    roles: dict[Role, tuple[ProviderEntry, ...]]

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
