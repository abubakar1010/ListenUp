"""Email templates and the SMTP adapter (#31: FR-ACC-3), without a mail server."""

import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, ClassVar

import pytest

from listenup.modules.notifications import emails
from listenup.modules.notifications.emails import EmailContent
from listenup.modules.notifications.smtp import SmtpTransport, build_message
from listenup.platform.config import Settings
from listenup.platform.jobs import PermanentError

LINK = "https://listenup.example/reset-password#token=abc_DEF-123"


def test_the_reset_email_has_the_link_in_both_parts() -> None:
    mail = emails.password_reset("learner@example.com", LINK, 60)

    assert mail.to == "learner@example.com"
    assert mail.subject == "Reset your ListenUp password"
    assert LINK in mail.text
    assert f'href="{LINK}"' in mail.html
    assert "within 1 hour" in mail.text
    assert "ignore this email" in mail.text


@pytest.mark.parametrize(
    ("minutes", "said"), [(60, "1 hour"), (120, "2 hours"), (30, "30 minutes"), (1, "1 minute")]
)
def test_the_lifetime_is_said_in_words(minutes: int, said: str) -> None:
    assert f"within {said}" in emails.password_reset("a@example.com", LINK, minutes).text


def test_values_cannot_inject_markup_into_the_html() -> None:
    mail = emails.password_reset("a@example.com", 'https://x.example/"><script>', 60)

    assert "<script>" not in mail.html
    assert "&quot;&gt;&lt;script&gt;" in mail.html


def test_the_message_is_plain_text_with_an_html_alternative() -> None:
    content = EmailContent("to@example.com", "Subject", "plain body\n", "<p>html body</p>\n")

    message = build_message(content, "ListenUp <no-reply@listenup.example>")

    assert message["To"] == "to@example.com"
    assert message["From"] == "ListenUp <no-reply@listenup.example>"
    assert message["Message-ID"].endswith("@listenup.example>")
    assert message.get_content_type() == "multipart/alternative"
    plain, rich = message.iter_parts()
    assert plain.get_content_type() == "text/plain"
    assert rich.get_content_type() == "text/html"


class FakeSmtp:
    instances: ClassVar[list["FakeSmtp"]] = []
    refuse = False

    def __init__(self, host: str, port: int, timeout: float, **kwargs: Any) -> None:
        self.address = (host, port)
        self.calls: list[str] = []
        self.sent: list[EmailMessage] = []
        FakeSmtp.instances.append(self)

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *exc: object) -> None:
        self.calls.append("quit")

    def starttls(self, context: object) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login:{user}:{password}")

    def send_message(self, message: EmailMessage) -> None:
        if FakeSmtp.refuse:
            raise smtplib.SMTPRecipientsRefused({message["To"]: (550, b"no such user")})
        self.calls.append("send")
        self.sent.append(message)


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSmtp]:
    FakeSmtp.instances = []
    FakeSmtp.refuse = False
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSmtp)
    return FakeSmtp


CONTENT = EmailContent("to@example.com", "Subject", "text", "<p>html</p>")


@pytest.mark.anyio
async def test_local_smtp_sends_without_tls_or_login(fake_smtp: type[FakeSmtp]) -> None:
    await SmtpTransport(Settings(smtp_host="mail", smtp_port=1025)).send(CONTENT)

    [server] = fake_smtp.instances
    assert server.address == ("mail", 1025)
    assert server.calls == ["send", "quit"]
    assert server.sent[0]["Subject"] == "Subject"


@pytest.mark.anyio
async def test_a_provider_gets_starttls_and_login(fake_smtp: type[FakeSmtp]) -> None:
    settings = Settings(
        smtp_security="starttls",
        smtp_username="apikey",
        smtp_password="s3cret",  # type: ignore[arg-type]
    )

    await SmtpTransport(settings).send(CONTENT)

    assert fake_smtp.instances[0].calls == ["starttls", "login:apikey:s3cret", "send", "quit"]


@pytest.mark.anyio
async def test_a_refused_recipient_is_not_retried(fake_smtp: type[FakeSmtp]) -> None:
    fake_smtp.refuse = True

    with pytest.raises(PermanentError):
        await SmtpTransport(Settings()).send(CONTENT)


def test_the_deletion_email_states_the_date_in_utc_and_how_to_restore() -> None:
    dhaka = timezone(timedelta(hours=6))
    # 02:30 on 12 October in Dhaka is 20:30 on 11 October in UTC.
    mail = emails.account_deletion(
        "learner@example.com",
        datetime(2026, 10, 12, 2, 30, tzinfo=dhaka),
        "https://listenup.example/sign-in",
    )

    assert mail.subject == "Your ListenUp account will be deleted on 11 October 2026"
    for part in (mail.text, mail.html):
        assert "11 October 2026, 20:30 UTC" in part
        assert "https://listenup.example/sign-in" in part
        assert "restore" in part
