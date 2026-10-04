"""Where database dumps are kept: an S3-compatible bucket, or a directory for drills.

Dumps are encrypted at rest by the storage provider (issue #97); credentials come
from the LISTENUP_S3_* settings in the environment.
"""

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import boto3
from botocore.config import Config

from listenup.platform.config import Settings

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client


@dataclass(frozen=True)
class StoredFile:
    key: str
    size: int
    modified: datetime


class BackupStore(Protocol):
    def upload(self, key: str, source: Path) -> None: ...
    def download(self, key: str, destination: Path) -> None: ...
    def list_files(self, prefix: str) -> list[StoredFile]: ...
    def delete(self, keys: list[str]) -> None: ...


class S3BackupStore:
    """The backup bucket (LISTENUP_BACKUP_BUCKET, else the media bucket)."""

    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.backup_bucket or settings.s3_bucket
        self._client: S3Client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def upload(self, key: str, source: Path) -> None:
        self._client.upload_file(str(source), self.bucket, key)

    def download(self, key: str, destination: Path) -> None:
        self._client.download_file(self.bucket, key, str(destination))

    def list_files(self, prefix: str) -> list[StoredFile]:
        found: list[StoredFile] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                found.append(StoredFile(item["Key"], item["Size"], item["LastModified"]))
        return found

    def delete(self, keys: list[str]) -> None:
        for start in range(0, len(keys), 1000):  # the S3 limit for one call
            batch = keys[start : start + 1000]
            self._client.delete_objects(
                Bucket=self.bucket, Delete={"Objects": [{"Key": key} for key in batch]}
            )


class DirectoryBackupStore:
    """A local directory with the same layout, for restore drills and tests."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        if key.startswith("/") or ".." in key.split("/"):
            raise ValueError(f"invalid key: {key!r}")
        return self.root / key

    def upload(self, key: str, source: Path) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    def download(self, key: str, destination: Path) -> None:
        shutil.copyfile(self._path(key), destination)

    def list_files(self, prefix: str) -> list[StoredFile]:
        if not self.root.exists():
            return []
        found = []
        for path in sorted(self.root.rglob("*")):
            key = path.relative_to(self.root).as_posix()
            if path.is_file() and key.startswith(prefix):
                stat = path.stat()
                found.append(
                    StoredFile(key, stat.st_size, datetime.fromtimestamp(stat.st_mtime, UTC))
                )
        return found

    def delete(self, keys: list[str]) -> None:
        for key in keys:
            self._path(key).unlink(missing_ok=True)
