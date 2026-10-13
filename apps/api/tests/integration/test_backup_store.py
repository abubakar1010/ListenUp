"""The backup bucket against a real S3-compatible server (#97, ADR 0032).

Uses a throwaway bucket on LISTENUP_S3_ENDPOINT_URL; skipped when no server is
reachable, unless LISTENUP_REQUIRE_S3=1 (CI).
"""

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from listenup.ops import backup
from listenup.ops.backup import prune, stamps
from listenup.ops.store import S3BackupStore
from listenup.platform.config import Settings

PREFIX = "backups/postgres/"


@pytest.fixture(scope="module")
def store() -> Iterator[S3BackupStore]:
    settings = Settings(backup_bucket=f"listenup-test-{uuid.uuid4().hex[:12]}")
    bucket = settings.backup_bucket
    assert bucket is not None
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
        client.create_bucket(Bucket=bucket)
    except (BotoCoreError, ClientError) as error:
        if os.environ.get("LISTENUP_REQUIRE_S3") == "1":
            raise
        pytest.skip(f"S3 storage is not reachable: {error}")

    yield S3BackupStore(settings)

    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            client.delete_object(Bucket=bucket, Key=obj["Key"])
    client.delete_bucket(Bucket=bucket)


def test_dumps_round_trip_and_expired_ones_are_removed(
    store: S3BackupStore, tmp_path: Path
) -> None:
    now = datetime.now(UTC)
    source = tmp_path / "dump"
    source.write_bytes(b"PGDMP fake dump")
    taken = {}
    for days in (20, 15, 1):
        stamp = (now - timedelta(days=days)).strftime(backup.STAMP_FORMAT)
        taken[days] = stamp
        store.upload(f"{PREFIX}{stamp}/{backup.DUMP_NAME}", source)
        store.upload(f"{PREFIX}{stamp}/{backup.MANIFEST_NAME}", source)

    assert stamps(store, PREFIX) == [taken[1], taken[15], taken[20]]
    assert sorted(prune(store, PREFIX, 14, now=now)) == sorted([taken[20], taken[15]])
    assert stamps(store, PREFIX) == [taken[1]]

    copy = tmp_path / "copy"
    store.download(f"{PREFIX}{taken[1]}/{backup.DUMP_NAME}", copy)
    assert copy.read_bytes() == b"PGDMP fake dump"
