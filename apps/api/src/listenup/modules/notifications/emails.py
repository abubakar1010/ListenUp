"""Email content: what each message says, rendered from our own template files.

Templates live in `notifications/templates/<name>.subject.txt`, `<name>.txt` and
`<name>.html` and use `$name` placeholders (string.Template). Values are escaped for
the HTML part, so a value can never inject markup.
"""

import html
from dataclasses import dataclass
from importlib import resources
from string import Template

_TEMPLATES = resources.files("listenup.modules.notifications").joinpath("templates")


@dataclass(frozen=True)
class EmailContent:
    to: str
    subject: str
    text: str
    html: str


def _template(name: str) -> Template:
    return Template(_TEMPLATES.joinpath(name).read_text(encoding="utf-8"))


def render(template: str, to: str, values: dict[str, str]) -> EmailContent:
    """Fill template `template`; raises KeyError when a placeholder has no value."""
    escaped = {key: html.escape(value) for key, value in values.items()}
    return EmailContent(
        to=to,
        subject=_template(f"{template}.subject.txt").substitute(values).strip(),
        text=_template(f"{template}.txt").substitute(values),
        html=_template(f"{template}.html").substitute(escaped),
    )


def password_reset(to: str, link: str, valid_minutes: int) -> EmailContent:
    """The reset email (FR-ACC-3): one link that works once, within the time stated."""
    return render("password_reset", to, {"link": link, "valid_for": _duration(valid_minutes)})


def _duration(minutes: int) -> str:
    if minutes % 60 == 0:
        hours = minutes // 60
        return "1 hour" if hours == 1 else f"{hours} hours"
    return "1 minute" if minutes == 1 else f"{minutes} minutes"
