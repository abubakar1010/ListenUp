"""Signing, URL reuse and safety checks of the storage adapter; no server needed."""

from urllib.parse import parse_qs, urlparse

import pytest

from listenup.platform.config import Settings
from listenup.platform.storage import S3Storage


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def make_storage(clock: Clock | None = None, **overrides: object) -> S3Storage:
    settings = Settings(signed_url_ttl_seconds=300, **overrides)  # type: ignore[arg-type]
    return S3Storage(settings, clock=clock or Clock())


def test_download_urls_are_reused_until_80_percent_of_their_lifetime() -> None:
    clock = Clock()
    storage = make_storage(clock)

    first = storage.signed_download("users/1/a.mp3")
    clock.now += 239
    assert storage.signed_download("users/1/a.mp3") == first
    clock.now += 2  # 241 s: past 80% of 300 s
    renewed = storage.signed_download("users/1/a.mp3")
    assert renewed != first
    assert renewed.expires_at == clock.now + 300


def test_urls_expire_in_minutes() -> None:
    url = make_storage().signed_download("users/1/a.mp3").url
    assert parse_qs(urlparse(url).query)["X-Amz-Expires"] == ["300"]


def test_a_short_lived_download_url_is_fresh_and_capped() -> None:
    """Blind's attempt-bound media (#62): never reused, never longer than the default."""
    clock = Clock()
    storage = make_storage(clock)
    cached = storage.signed_download("users/1/a.mp3")

    short = storage.signed_download("users/1/a.mp3", ttl_seconds=90)
    capped = storage.signed_download("users/1/a.mp3", ttl_seconds=3_600)

    assert short != cached
    assert parse_qs(urlparse(short.url).query)["X-Amz-Expires"] == ["90"]
    assert short.expires_at == clock.now + 90
    assert parse_qs(urlparse(capped.url).query)["X-Amz-Expires"] == ["300"]
    assert storage.signed_download("users/1/a.mp3") == cached


def test_upload_urls_are_bound_to_the_content_type() -> None:
    signed = make_storage().signed_upload("users/1/upload.webm", "audio/webm")

    assert signed.method == "PUT"
    assert signed.headers == {"Content-Type": "audio/webm"}
    assert "content-type" in parse_qs(urlparse(signed.url).query)["X-Amz-SignedHeaders"][0]


def test_signed_urls_use_the_public_endpoint() -> None:
    storage = make_storage(
        s3_endpoint_url="http://storage:9000", s3_public_endpoint_url="http://localhost:9000"
    )
    assert storage.signed_download("users/1/a.mp3").url.startswith("http://localhost:9000/")


@pytest.mark.parametrize("key", ["", "/abs", "users/../secrets"])
def test_unsafe_keys_are_refused(key: str) -> None:
    with pytest.raises(ValueError):
        make_storage().signed_download(key)


@pytest.mark.parametrize("prefix", ["", "/", "users/12"])
@pytest.mark.anyio
async def test_delete_needs_a_folder_prefix(prefix: str) -> None:
    with pytest.raises(ValueError):
        await make_storage().delete_prefix(prefix)


def test_upload_urls_can_be_bound_to_the_exact_size() -> None:
    signed = make_storage().signed_upload("users/1/uploads/a.mp3", "audio/mpeg", content_length=42)

    signed_headers = parse_qs(urlparse(signed.url).query)["X-Amz-SignedHeaders"][0]
    assert "content-length" in signed_headers.split(";")
    # Clients send Content-Length themselves; browsers refuse to let a page set it.
    assert signed.headers == {"Content-Type": "audio/mpeg"}
