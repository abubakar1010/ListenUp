"""Text AI over the OpenAI-compatible chat API (Architecture 7.3, NFR-AI-2, NFR-AI-4).

One adapter covers the hosted free tier (Groq) and local servers (Ollama, llama.cpp,
vLLM); `ai.yaml` registers it under several provider ids so each keeps its own quota
counters. It talks plain HTTP with httpx, so no vendor SDK is imported. Everything that
varies is an option: `base_url`, `api_key_env` (the NAME of an environment variable; the
key never appears in a file), `structured_output`, `reasoning_effort`, `seed` and
`deployment_version` (for example a model digest); the logged version names all but the
URL and key.

The adapter sends temperature 0 and caps the reply at the entry's `output_token_limit`,
asks for schema-constrained JSON where the server supports it, and validates every reply
against the task's Pydantic model. It never retries by itself: an invalid reply is an
error the gateway answers with the next provider, and each retry is admitted afresh
(ADR 0041). Errors carry no response text, which can echo learner words.
"""

import asyncio
import ipaddress
import json
import os
import re
import socket
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from listenup.ai.config import ProviderEntry
from listenup.ai.errors import PermanentProviderError, TransientProviderError
from listenup.ai.ports import Provenance, TextGeneration, TextTask, Usage
from listenup.ai.prompt_files import PROMPTS_DIR, load_prompt
from listenup.ai.prompt_render import render_messages
from listenup.ai.tasks import TASK_MODELS

_RETRYABLE_STATUS = frozenset({408, 429})
_FENCE = re.compile(r"\A```(?:json)?\s*(.*?)\s*```\Z", re.DOTALL)
# The gateway accepts only these characters in a version it compares (gateway.py).
_VERSION_CHARS = r"[A-Za-z0-9_.+:()-]{1,96}"


class _Options(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str = Field(min_length=1)
    # Only a variable named for a Text AI key, so no other secret (database URL, session
    # secret) can be configured into the Authorization header of a provider request.
    api_key_env: str | None = Field(
        default=None, max_length=64, pattern=r"^LISTENUP_AI_[A-Z0-9]+(?:_[A-Z0-9]+)*_API_KEY$"
    )
    structured_output: Literal["json_schema", "json_object", "none"] = "json_schema"
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    seed: int | None = Field(default=None, ge=-(2**63), le=2**63 - 1)  # fits the version
    deployment_version: str | None = Field(default=None, pattern=f"^{_VERSION_CHARS}$")


def parse_options(entry: ProviderEntry) -> _Options:
    """The validated options of an entry; raises ValueError for anything unsafe, such as a
    hosted server over plain HTTP, which would send learner text in the clear."""
    try:
        options = _Options.model_validate(entry.options)
    except ValidationError as error:
        raise ValueError("invalid text AI options") from error
    parts = urlsplit(options.base_url)
    allowed = ("https", "http") if entry.local else ("https",)
    if parts.scheme not in allowed or not parts.hostname or parts.username or parts.password:
        raise ValueError("base_url must be https (http only for a local server), no credentials")
    if parts.query or parts.fragment:
        raise ValueError("base_url must not carry a query")
    if entry.local and not _is_local_url(options.base_url, parts.hostname):
        raise ValueError("a local entry must be on this host or the private network")
    return options.model_copy(update={"base_url": options.base_url.rstrip("/")})


_SINGLE_LABEL = re.compile(r"[a-z0-9_-]+")
_DOMAIN = re.compile(r"[a-z0-9_-]+(?:\.[a-z0-9_-]+)+")


def _is_local_url(base_url: str, host: str) -> bool:
    """The host is judged as the HTTP client will read it, not only as `urlsplit` does:
    `evil。com` (ideographic full stop) has no ASCII dot to `urlsplit` but is `evil.com` to
    httpx, so the two must agree or the entry is refused."""
    try:
        client_host = httpx.URL(base_url).host
    except httpx.InvalidURL:
        return False
    return client_host == host and _is_local_host(host)


# Local-use NAT64 (RFC 8215): Python counts it as private, but a NAT64 gateway forwards it
# to the public IPv4 address it carries.
_NAT64_LOCAL_USE = ipaddress.IPv6Network("64:ff9b:1::/48")


def _is_local_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        elif (
            address.sixtofour is not None
            or address.teredo is not None
            or address in _NAT64_LOCAL_USE
        ):
            return False
    return address.is_private  # includes loopback and link-local


def _is_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _is_local_host(host: str) -> bool:
    """`local: true` skips the consent, retention and region checks (policy.eligible) and
    allows plain HTTP, so it must name this host or the private network: a Compose service
    name, `localhost`, a `.internal` name, or a private, loopback or link-local address.
    Only plain ASCII names qualify. A single label that the resolver reads as an address
    (`134744072`, `0x08080808`) is refused, as are IPv4-mapped, 6to4, Teredo and local-use
    NAT64 addresses that carry another address inside. A name is also checked where it
    resolves, per request (`OpenAICompatibleTextAI._check_resolved`), because a resolver
    search domain can complete a single label."""
    if not host.isascii():
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return _is_local_address(address)
    if host.endswith((".internal", ".localhost")):
        return _DOMAIN.fullmatch(host) is not None
    if _SINGLE_LABEL.fullmatch(host) is None:
        return False
    try:
        socket.inet_aton(host)
    except OSError:
        return True  # a name, resolved by the Compose network or a search domain
    return False


def version_for(entry: ProviderEntry) -> str:
    """The deployment version logged and compared with the result (ADR 0041): trusted
    configuration only, never taken from the server's reply. It names every option that
    changes the output, so changing one changes what is recorded (NFR-AI-5)."""
    options = parse_options(entry)
    version = f"openai-chat-v1; structured={options.structured_output}"
    if options.reasoning_effort is not None:
        version += f"; reasoning={options.reasoning_effort}"
    if options.seed is not None:
        version += f"; seed={options.seed}"
    if options.deployment_version:
        version += f"; deployment={options.deployment_version}"
    return version


Resolver = Callable[[str], Awaitable[list[str]]]


async def _resolve(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


class OpenAICompatibleTextAI:
    def __init__(
        self,
        entry: ProviderEntry,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        environ: Mapping[str, str] | None = None,
        prompts_root: Path = PROMPTS_DIR,
        resolver: Resolver | None = None,
    ) -> None:
        self._entry = entry
        self._prompts_root = prompts_root
        self._options = parse_options(entry)
        self._transport = transport
        self._environ = environ
        self._version = version_for(entry)
        # Only a local entry on a name is resolved, whatever transport is passed; tests
        # pass a fake resolver.
        host = urlsplit(self._options.base_url).hostname or ""
        self._resolved_host = host if entry.local and not _is_address(host) else None
        self._resolver = resolver or _resolve

    def _headers(self) -> dict[str, str]:
        name = self._options.api_key_env
        if name is None:
            return {}
        key = (self._environ if self._environ is not None else os.environ).get(name)
        if not key:
            raise PermanentProviderError("API key is not configured")
        return {"Authorization": f"Bearer {key}"}

    def _body(self, task: TextTask, input: Mapping[str, Any]) -> dict[str, Any]:
        spec = load_prompt(task.name, task.version, root=self._prompts_root)
        messages = render_messages(spec, input)
        options = self._options
        body: dict[str, Any] = {
            "model": self._entry.model,
            "temperature": 0,
            "max_tokens": self._entry.output_token_limit,
            "stream": False,
        }
        if options.seed is not None:
            body["seed"] = options.seed
        if options.reasoning_effort is not None:
            body["reasoning_effort"] = options.reasoning_effort
        if options.structured_output == "json_schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": task.name, "strict": True, "schema": spec.output_schema},
            }
        else:
            if options.structured_output == "json_object":
                body["response_format"] = {"type": "json_object"}
            messages[0]["content"] += (
                "\n\nReply with one JSON object that matches this JSON Schema, and nothing "
                f"else:\n{json.dumps(spec.output_schema)}"
            )
        body["messages"] = messages
        return body

    async def _check_resolved(self) -> str | None:
        """A local entry skips the consent, retention and region checks, so the name it
        uses must lead to this host or the private network, whatever a resolver search
        domain makes of a single label. Checked before any learner text is sent; returns
        the address to connect to, so the connection cannot resolve to another one."""
        if self._resolved_host is None:
            return None
        try:
            addresses = await self._resolver(self._resolved_host)
        except OSError:
            raise TransientProviderError("local text AI host did not resolve") from None
        if not addresses or not all(_is_local_address(ipaddress.ip_address(a)) for a in addresses):
            raise PermanentProviderError("local text AI host resolves outside the private network")
        return addresses[0]

    async def _post(self, body: dict[str, Any], headers: dict[str, str]) -> Any:
        url = httpx.URL(f"{self._options.base_url}/chat/completions")
        extensions: dict[str, Any] = {}
        if (address := await self._check_resolved()) is not None:
            # Connect to the checked address; the name stays in the Host header and the TLS
            # server name, so an https local server still proves its certificate.
            headers = {**headers, "Host": url.netloc.decode("ascii")}
            extensions["sni_hostname"] = url.host
            url = url.copy_with(host=address)
        try:
            # trust_env=False: a proxy from the environment would receive the learner text
            # instead of the server checked above (NFR-AI-7).
            async with httpx.AsyncClient(
                transport=self._transport, timeout=self._entry.timeout_seconds, trust_env=False
            ) as client:
                response = await client.post(url, json=body, headers=headers, extensions=extensions)
        except httpx.TimeoutException:
            raise TimeoutError("text AI request timed out") from None
        except httpx.TransportError:
            raise TransientProviderError("text AI connection failed") from None
        status = response.status_code
        if status in _RETRYABLE_STATUS or status >= 500:
            raise TransientProviderError(f"text AI server answered {status}")
        if status >= 300:
            raise PermanentProviderError(f"text AI server answered {status}")
        try:
            return response.json()
        except ValueError:
            raise ValueError("malformed provider response") from None

    def _content(self, payload: Any) -> str:
        try:
            choice = payload["choices"][0]
            message = choice["message"]
            content = message["content"]
            finish, refusal = choice.get("finish_reason"), message.get("refusal")
        except (KeyError, IndexError, TypeError, AttributeError):
            raise ValueError("malformed provider response") from None
        if refusal or finish == "length" or not isinstance(content, str) or not content.strip():
            raise ValueError("provider gave no complete reply")
        if self._options.structured_output != "json_schema" and (
            fenced := _FENCE.match(content.strip())
        ):
            return fenced.group(1)
        return content

    @staticmethod
    def _usage(payload: Any) -> Usage | None:
        try:
            raw = payload["usage"]
            return Usage(
                input_tokens=raw["prompt_tokens"],
                output_tokens=raw["completion_tokens"],
                cache_tokens=(raw.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
                reasoning_tokens=(raw.get("completion_tokens_details") or {}).get(
                    "reasoning_tokens", 0
                ),
            )
        except (KeyError, TypeError, AttributeError, ValidationError):
            return None  # unknown usage stays reserved at the full budget (ADR 0041)

    async def generate[T: BaseModel](
        self, task: TextTask, input: Mapping[str, Any], output_schema: type[T]
    ) -> TextGeneration[T]:
        if TASK_MODELS.get(task.name) is not output_schema:
            raise ValueError("output schema does not belong to the task")
        body = self._body(task, input)
        payload = await self._post(body, self._headers())
        value = output_schema.model_validate_json(self._content(payload))
        result: type[TextGeneration[T]] = TextGeneration[output_schema]  # type: ignore[valid-type]
        return result(
            provenance=Provenance(
                provider=self._entry.provider, model=self._entry.model, version=self._version
            ),
            task=task.name,
            prompt_version=task.version,
            value=value,
            usage=self._usage(payload),
        )
