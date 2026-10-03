"""S3-compatible object storage (ADR 0005, ADR 0012).

The bucket is never public. The browser reaches objects only through short-lived
signed URLs issued after an ownership check (Architecture 8). Signing needs no network
call; listing and deleting do, and run in a worker thread so they never block the
event loop.

Signed download URLs are reused until 80% of their lifetime has passed, from a small
in-memory LRU cache, so a page that asks for the same file repeatedly gets the same
URL and the browser cache keeps working.
"""

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import anyio.to_thread
import boto3
from botocore.config import Config

from listenup.platform.config import Settings

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client

REUSE_FRACTION = 0.8
CACHE_SIZE = 10_000
DELETE_BATCH = 1000  # the S3 limit for one DeleteObjects call


@dataclass(frozen=True)
class SignedUrl:
    url: str
    method: str
    expires_at: float  # Unix time
    headers: dict[str, str]  # headers the client must send with the request


class Storage(Protocol):
    def signed_upload(self, key: str, content_type: str) -> SignedUrl: ...
    def signed_download(self, key: str, download_name: str | None = None) -> SignedUrl: ...
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def delete_prefix(self, prefix: str) -> int: ...


def check_key(key: str) -> None:
    if not key or key.startswith("/") or ".." in key.split("/"):
        raise ValueError(f"invalid storage key: {key!r}")


class S3Storage:
    def __init__(
        self,
        settings: Settings,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.bucket = settings.s3_bucket
        self.ttl = settings.signed_url_ttl_seconds
        self._clock = clock
        self._cache: OrderedDict[tuple[str, str | None], SignedUrl] = OrderedDict()
        self._client = self._make_client(settings, settings.s3_endpoint_url)
        # Signed URLs must name the host the browser can reach.
        self._signer = self._make_client(
            settings, settings.s3_public_endpoint_url or settings.s3_endpoint_url
        )

    @staticmethod
    def _make_client(settings: Settings, endpoint_url: str) -> "S3Client":
        return boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            # Path-style addressing works with every S3-compatible server.
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def signed_upload(self, key: str, content_type: str) -> SignedUrl:
        """A URL the browser can PUT one object to, with this exact Content-Type."""
        check_key(key)
        url = self._signer.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=self.ttl,
        )
        return SignedUrl(url, "PUT", self._clock() + self.ttl, {"Content-Type": content_type})

    def signed_download(self, key: str, download_name: str | None = None) -> SignedUrl:
        """A URL the browser can GET one object from; reused while fresh."""
        check_key(key)
        cache_key = (key, download_name)
        now = self._clock()
        cached = self._cache.get(cache_key)
        if cached is not None and now < cached.expires_at - self.ttl * (1 - REUSE_FRACTION):
            self._cache.move_to_end(cache_key)
            return cached

        params = {"Bucket": self.bucket, "Key": key}
        if download_name is not None:
            safe = download_name.replace('"', "")
            params["ResponseContentDisposition"] = f'attachment; filename="{safe}"'
        url = self._signer.generate_presigned_url("get_object", Params=params, ExpiresIn=self.ttl)
        signed = SignedUrl(url, "GET", now + self.ttl, {})
        self._cache[cache_key] = signed
        self._cache.move_to_end(cache_key)
        while len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return signed

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        check_key(key)
        await anyio.to_thread.run_sync(
            lambda: self._client.put_object(
                Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
            )
        )

    async def delete_prefix(self, prefix: str) -> int:
        """Delete every object under a folder-like prefix; returns how many were deleted.

        The prefix must end with "/" so that `users/12` can never also delete
        `users/123/...`, and an empty prefix (the whole bucket) is refused.
        """
        if not prefix.endswith("/") or prefix == "/":
            raise ValueError(f"prefix must be a non-empty folder ending in '/': {prefix!r}")
        check_key(prefix.rstrip("/"))
        deleted = await anyio.to_thread.run_sync(self._delete_prefix_sync, prefix)
        self._forget_prefix(prefix)
        return deleted

    def _delete_prefix_sync(self, prefix: str) -> int:
        deleted = 0
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys = [obj["Key"] for obj in page.get("Contents", [])]
            for start in range(0, len(keys), DELETE_BATCH):
                batch = keys[start : start + DELETE_BATCH]
                result = self._client.delete_objects(
                    Bucket=self.bucket,
                    Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
                )
                errors = result.get("Errors", [])
                if errors:
                    raise RuntimeError(f"could not delete {len(errors)} objects under {prefix}")
                deleted += len(batch)
        return deleted

    def _forget_prefix(self, prefix: str) -> None:
        for cache_key in [k for k in self._cache if k[0].startswith(prefix)]:
            del self._cache[cache_key]
