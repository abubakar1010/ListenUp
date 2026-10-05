"""Errors of the AI layer. Callers catch `AIUnavailable` only (Architecture 7.2)."""

from listenup.ai.ports import Role


class AIUnavailable(Exception):
    """No configured provider produced a result. Callers show "feedback delayed" or
    "unavailable" and keep the learner's data; a job may retry later."""

    def __init__(self, role: Role, reason: str) -> None:
        super().__init__(f"{role.value}: {reason}")
        self.role = role
        self.reason = reason


class TransientProviderError(Exception):
    """An adapter's call failed in a way that may pass on retry (network error, 5xx,
    rate limit). The gateway retries it with backoff."""


class AIConfigError(Exception):
    """`ai.yaml` is invalid or names a provider no adapter implements for that role."""
