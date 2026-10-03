"""SMTP adapter: sends an email through any standard SMTP server.

Locally that is Mailpit; in production any transactional provider's SMTP endpoint
(SRS 7.2). The standard library client is blocking, so it runs in a worker thread.
"""

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

import anyio.to_thread

from listenup.modules.notifications.emails import EmailContent
from listenup.platform.config import Settings
from listenup.platform.jobs import PermanentError


def build_message(content: EmailContent, sender: str) -> EmailMessage:
    """A multipart/alternative message: plain text first, HTML as the richer part."""
    message = EmailMessage()
    message["From"] = sender
    message["To"] = content.to
    message["Subject"] = content.subject
    message["Date"] = formatdate(localtime=False)
    domain = parseaddr(sender)[1].rpartition("@")[2] or None
    message["Message-ID"] = make_msgid(domain=domain)
    message.set_content(content.text)
    message.add_alternative(content.html, subtype="html")
    return message


class SmtpTransport:
    def __init__(self, settings: Settings) -> None:
        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.security = settings.smtp_security
        self.timeout = settings.smtp_timeout_seconds
        self.username = settings.smtp_username
        self.password = settings.smtp_password
        self.sender = settings.smtp_sender

    async def send(self, content: EmailContent) -> None:
        message = build_message(content, self.sender)
        await anyio.to_thread.run_sync(self._send, message)

    def _send(self, message: EmailMessage) -> None:
        context = ssl.create_default_context()
        client: smtplib.SMTP
        if self.security == "ssl":
            client = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=context)
        else:
            client = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        with client:
            if self.security == "starttls":
                client.starttls(context=context)
            if self.username:
                password = self.password.get_secret_value() if self.password else ""
                client.login(self.username, password)
            try:
                client.send_message(message)
            except smtplib.SMTPRecipientsRefused as error:
                # The address itself is refused; retrying cannot help.
                raise PermanentError("the mail server refused the recipient") from error
