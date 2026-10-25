"""Refuse a public bucket before a deploy (#112; Architecture 12.1, NFR-SEC-1).

Learner media and database dumps live in private buckets; the browser only ever gets
signed URLs. Provider settings differ (ACLs, bucket policies, public-access blocks,
dashboard toggles), so the decisive test is the same everywhere: an unsigned request
must be refused. For each bucket the check writes a small probe object with the
bucket's own key, asks every endpoint it is served from (the internal one and the
one in signed URLs) to list the bucket and to read the probe without credentials,
and removes the probe. Any 2xx or 3xx answer means the bucket is public. Where the
provider supports it, its own bucket policy status must not say public either.

    python -m listenup.ops.storage_check

prints one JSON line per bucket and exits 0 when every bucket is private, 1 when one
is public, and 2 when a check could not be completed (which never counts as a pass).
"""

import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, Protocol

import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from listenup.ops.store import backup_bucket_name, backup_credentials
from listenup.platform.config import Settings, get_settings

PROBE_KEY = "ops/public-access-probe.txt"
REFUSED = (401, 403)


class ProbeClient(Protocol):
    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> object: ...
    def delete_object(self, *, Bucket: str, Key: str) -> object: ...
    def get_bucket_policy_status(self, *, Bucket: str) -> Any: ...


@dataclass(frozen=True)
class BucketTarget:
    label: str
    bucket: str
    endpoints: tuple[str, ...]
    client: ProbeClient


@dataclass
class BucketReport:
    label: str
    bucket: str
    public: list[str]
    errors: list[str]
    policy: str


def _code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", "unknown"))


def _anonymous(
    http: httpx.Client, endpoint: str, what: str, url: str, report: BucketReport
) -> None:
    try:
        status = http.get(url, follow_redirects=False).status_code
    except httpx.HTTPError as error:
        report.errors.append(f"{endpoint}: anonymous {what} failed: {type(error).__name__}")
        return
    if status in REFUSED:
        return
    if 200 <= status < 400:
        report.public.append(f"{endpoint}: anonymous {what} answered {status}")
    else:
        report.errors.append(f"{endpoint}: anonymous {what} answered {status}")


def _policy(target: BucketTarget, report: BucketReport) -> None:
    try:
        status = target.client.get_bucket_policy_status(Bucket=target.bucket)
    except ClientError as error:
        code = _code(error)
        report.policy = (
            "no bucket policy" if code == "NoSuchBucketPolicy" else f"unsupported ({code})"
        )
        return
    except BotoCoreError as error:
        report.policy = f"unsupported ({type(error).__name__})"
        return
    if status.get("PolicyStatus", {}).get("IsPublic"):
        report.policy = "public"
        report.public.append("the provider reports the bucket policy as public")
    else:
        report.policy = "not public"


def check_bucket(target: BucketTarget, http: httpx.Client) -> BucketReport:
    report = BucketReport(target.label, target.bucket, [], [], "not checked")
    try:
        target.client.put_object(
            Bucket=target.bucket, Key=PROBE_KEY, Body=b"ListenUp public access probe\n"
        )
    except ClientError as error:
        report.errors.append(f"could not write the probe object: {_code(error)}")
        return report
    except BotoCoreError as error:
        report.errors.append(f"could not write the probe object: {type(error).__name__}")
        return report
    try:
        for endpoint in target.endpoints:
            base = f"{endpoint.rstrip('/')}/{target.bucket}"
            _anonymous(http, endpoint, "list", f"{base}?list-type=2&max-keys=1", report)
            _anonymous(http, endpoint, "read of the probe", f"{base}/{PROBE_KEY}", report)
        _policy(target, report)
    finally:
        target.client.delete_object(Bucket=target.bucket, Key=PROBE_KEY)
    return report


def exit_code(reports: Sequence[BucketReport]) -> int:
    if any(report.public for report in reports):
        return 1
    if not reports or any(report.errors for report in reports):
        return 2
    return 0


def _client(endpoint: str, region: str, access_key: str, secret_key: str) -> ProbeClient:
    client: ProbeClient = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    return client


def targets(settings: Settings) -> list[BucketTarget]:
    """The media bucket on its internal and browser-facing endpoints, and the backup
    bucket when it is a separate bucket (always, outside local and test runs)."""
    endpoints = tuple(
        dict.fromkeys(
            url for url in (settings.s3_endpoint_url, settings.s3_public_endpoint_url) if url
        )
    )
    media = _client(
        settings.s3_endpoint_url,
        settings.s3_region,
        settings.s3_access_key,
        settings.s3_secret_key.get_secret_value(),
    )
    found = [BucketTarget("media", settings.s3_bucket, endpoints, media)]
    backup_bucket = backup_bucket_name(settings)
    if backup_bucket != settings.s3_bucket:
        endpoint = settings.backup_s3_endpoint_url or settings.s3_endpoint_url
        access_key, secret_key = backup_credentials(settings)
        region = settings.backup_s3_region or settings.s3_region
        client = _client(endpoint, region, access_key, secret_key)
        found.append(BucketTarget("backup", backup_bucket, (endpoint,), client))
    return found


def _http_client() -> httpx.Client:
    # No proxy from the environment: the question is what the bucket answers anyone.
    return httpx.Client(timeout=10.0, trust_env=False)


def main(argv: list[str] | None = None) -> int:
    del argv  # no options; settings come from the environment
    reports = []
    with _http_client() as http:
        for target in targets(get_settings()):
            report = check_bucket(target, http)
            reports.append(report)
            print(json.dumps(asdict(report)))
    return exit_code(reports)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
