"""Content-free routing context. Callers never supply learner identity here."""

from pydantic import BaseModel, ConfigDict, Field

from listenup.ai.config import ProviderEntry
from listenup.ai.ports import Role


class CallContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    queue_delay_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    audio_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    region: str | None = None
    population: str | None = None
    consent: bool = False
    round: int | None = Field(default=None, ge=1, le=3)


def eligible(entry: ProviderEntry, context: CallContext, role: Role) -> bool:
    if not entry.enabled or entry.trains_on_inputs is not False:
        return False
    if entry.local:
        return role in (Role.TRANSCRIPTION, Role.ALIGNMENT) or entry.accepted
    return (
        bool(entry.limits.get("day"))
        and bool(entry.limits.get("month"))
        and entry.accepted
        and entry.retention_verified
        and context.consent
        and context.region in entry.regions
        and context.population in entry.populations
    )
