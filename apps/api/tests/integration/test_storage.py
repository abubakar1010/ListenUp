"""Storage adapter against a real S3-compatible server (acceptance criteria of #25).

Uses the server at LISTENUP_S3_ENDPOINT_URL (SeaweedFS in Docker Compose and CI) and a
throwaway bucket. Skipped when no server is reachable, unless LISTENUP_REQUIRE_S3=1.
"""

import os
import uuid
from collections.abc import Iterator

import boto3
import httpx
import pytest
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from listenup.platform.config import Settings
from listenup.platform.storage import S3Storage


@pytest.fixture(scope="module")
def storage() -> Iterator[S3Storage]:
    settings = Settings(s3_bucket=f"listenup-test-{uuid.uuid4().hex[:12]}")
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        config=Config(
            s3={"addressing_style": "path"}, connect_timeout=3, retries={"max_attempts": 1}
        ),
    )
    try:
        client.create_bucket(Bucket=settings.s3_bucket)
    except (BotoCoreError, ClientError) as error:
        if os.environ.get("LISTENUP_REQUIRE_S3") == "1":
            raise
        pytest.skip(f"S3 storage is not reachable: {error}")

    yield S3Storage(settings)

    for page in client.get_paginator("list_objects_v2").paginate(Bucket=settings.s3_bucket):
        for obj in page.get("Contents", []):
            client.delete_object(Bucket=settings.s3_bucket, Key=obj["Key"])
    client.delete_bucket(Bucket=settings.s3_bucket)


def test_a_signed_put_uploads_and_a_signed_get_downloads(storage: S3Storage) -> None:
    upload = storage.signed_upload("users/1/recording.webm", "audio/webm")
    put = httpx.put(upload.url, content=b"voice", headers=upload.headers)
    assert put.status_code == 200

    download = storage.signed_download("users/1/recording.webm")
    got = httpx.get(download.url)
    assert got.status_code == 200
    assert got.content == b"voice"


def test_an_unsigned_get_is_refused(storage: S3Storage) -> None:
    signed = storage.signed_download("users/1/recording.webm")
    unsigned = signed.url.split("?", 1)[0]
    assert httpx.get(unsigned).status_code == 403


@pytest.mark.anyio
async def test_delete_by_prefix_removes_only_that_folder(storage: S3Storage) -> None:
    for name in ("a", "b", "c"):
        await storage.put(f"users/7/{name}.mp3", b"x", "audio/mpeg")
    await storage.put("users/77/keep.mp3", b"x", "audio/mpeg")

    deleted = await storage.delete_prefix("users/7/")

    assert deleted == 3
    assert httpx.get(storage.signed_download("users/7/a.mp3").url).status_code == 404
    assert httpx.get(storage.signed_download("users/77/keep.mp3").url).status_code == 200
