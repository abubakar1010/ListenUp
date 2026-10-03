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
