"""Outgoing email (Architecture 4.1). The only way other modules reach notifications.

Sending is slow and can fail, so callers send from background jobs, never while
handling a request. The transport is the SMTP adapter unless something else was
configured (tests use an in-memory one).
"""

from typing import Protocol

from listenup.modules.notifications import emails
from listenup.modules.notifications.emails import EmailContent
from listenup.modules.notifications.smtp import SmtpTransport
from listenup.platform.config import get_settings

__all__ = ["EmailContent", "EmailTransport", "send_password_reset", "use_transport"]


class EmailTransport(Protocol):
    async def send(self, content: EmailContent) -> None: ...


_transport: list[EmailTransport] = []


def use_transport(transport: EmailTransport | None) -> None:
    """Send through `transport` from now on; None goes back to SMTP from the settings."""
    _transport.clear()
    if transport is not None:
        _transport.append(transport)


def _current() -> EmailTransport:
    if not _transport:
        _transport.append(SmtpTransport(get_settings()))
    return _transport[0]


async def send_password_reset(to: str, link: str, valid_minutes: int) -> None:
    """Email a password reset link (FR-ACC-3)."""
    await _current().send(emails.password_reset(to, link, valid_minutes))
