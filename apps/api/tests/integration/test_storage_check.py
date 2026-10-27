"""The bucket privacy check against a real S3-compatible server (#112).

Uses a throwaway bucket on LISTENUP_S3_ENDPOINT_URL; skipped when no server is
reachable, unless LISTENUP_REQUIRE_S3=1 (CI).
"""

import os
import uuid
from collections.abc import Iterator

import boto3
import httpx
import pytest
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from listenup.ops.storage_check import PROBE_KEY, check_bucket, exit_code, targets
from listenup.platform.config import Settings


@pytest.fixture
def settings() -> Iterator[Settings]:
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

    yield settings

    remaining = client.list_objects_v2(Bucket=settings.s3_bucket).get("Contents", [])
    for obj in remaining:
        client.delete_object(Bucket=settings.s3_bucket, Key=obj["Key"])
    client.delete_bucket(Bucket=settings.s3_bucket)
    assert remaining == [], "the probe object must not be left behind"


def test_a_private_bucket_refuses_unsigned_requests_and_passes(settings: Settings) -> None:
    [media] = targets(settings)

    with httpx.Client(timeout=10.0, trust_env=False) as http:
        report = check_bucket(media, http)

    assert report.public == []
    assert report.errors == []
    assert exit_code([report]) == 0


def test_the_probe_really_exists_while_unsigned_reads_are_refused(settings: Settings) -> None:
    # Guards against a check that "passes" because the probe never reached the bucket:
    # a signed read of the same key succeeds where the anonymous one was refused.
    [media] = targets(settings)
    media.client.put_object(Bucket=settings.s3_bucket, Key=PROBE_KEY, Body=b"x")
    url = f"{settings.s3_endpoint_url}/{settings.s3_bucket}/{PROBE_KEY}"
    try:
        with httpx.Client(timeout=10.0, trust_env=False) as http:
            assert http.get(url).status_code in (401, 403)
        signed = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            config=Config(s3={"addressing_style": "path"}),
        )
        assert signed.get_object(Bucket=settings.s3_bucket, Key=PROBE_KEY)["Body"].read() == b"x"
    finally:
        media.client.delete_object(Bucket=settings.s3_bucket, Key=PROBE_KEY)
