"""The bucket privacy check run before every deploy (#112; Architecture 12.1, NFR-SEC-1).

Anonymous requests go through httpx's MockTransport, signed probe writes through a
fake client, so every provider answer can be played without a storage server.
"""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from botocore.exceptions import ClientError
from pydantic import SecretStr

from listenup.ops.storage_check import (
    PROBE_KEY,
    BucketReport,
    BucketTarget,
    check_bucket,
    exit_code,
    targets,
)
from listenup.platform.config import Settings

PRODUCTION = {
    "environment": "production",
    "analytics_hmac_key": SecretStr("a-stable-production-analytics-key-123"),
    "terms_version": "terms-2026-10-01",
    "privacy_version": "privacy-2026-10-01",
    "voice_consent_version": "voice-2026-10-01",
}


class FakeWriter:
    def __init__(self, policy: dict[str, Any] | Exception | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.policy = policy

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> object:
        self.calls.append(("put", Key))
        return {}

    def delete_object(self, *, Bucket: str, Key: str) -> object:
        self.calls.append(("delete", Key))
        return {}

    def get_bucket_policy_status(self, *, Bucket: str) -> dict[str, Any]:
        if isinstance(self.policy, Exception):
            raise self.policy
        if self.policy is None:
            raise client_error("NoSuchBucketPolicy")
        return self.policy


def client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "GetBucketPolicyStatus")


def answering(
    list_status: int = 403, get_status: int = 403, seen: list[httpx.Request] | None = None
) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path.endswith(PROBE_KEY):
            return httpx.Response(get_status)
        return httpx.Response(list_status)

    return httpx.Client(transport=httpx.MockTransport(handle))


def target(
    writer: FakeWriter, endpoints: tuple[str, ...] = ("https://s3.example",)
) -> BucketTarget:
    return BucketTarget("media", "listenup-media", endpoints, writer)


def test_a_bucket_that_refuses_anonymous_list_and_read_is_private() -> None:
    writer = FakeWriter()

    report = check_bucket(target(writer), answering())

    assert report.public == []
    assert report.errors == []
    assert writer.calls == [("put", PROBE_KEY), ("delete", PROBE_KEY)]


def test_401_counts_as_a_refusal_too() -> None:
    report = check_bucket(target(FakeWriter()), answering(list_status=401, get_status=401))

    assert report.public == []
    assert report.errors == []


def test_anonymous_requests_carry_no_credentials_and_use_path_style() -> None:
    seen: list[httpx.Request] = []

    check_bucket(target(FakeWriter()), answering(seen=seen))

    assert [str(request.url) for request in seen] == [
        "https://s3.example/listenup-media?list-type=2&max-keys=1",
        f"https://s3.example/listenup-media/{PROBE_KEY}",
    ]
    assert all("authorization" not in request.headers for request in seen)
    assert all("x-amz-security-token" not in request.headers for request in seen)


def test_a_bucket_that_lists_for_anyone_is_public() -> None:
    report = check_bucket(target(FakeWriter()), answering(list_status=200))

    assert report.public == ["https://s3.example: anonymous list answered 200"]


def test_a_bucket_whose_objects_anyone_can_read_is_public() -> None:
    report = check_bucket(target(FakeWriter()), answering(get_status=200))

    assert report.public == ["https://s3.example: anonymous read of the probe answered 200"]


def test_a_redirect_to_the_object_counts_as_readable() -> None:
    report = check_bucket(target(FakeWriter()), answering(get_status=307))

    assert report.public == ["https://s3.example: anonymous read of the probe answered 307"]


def test_every_endpoint_is_probed_so_the_browser_facing_one_cannot_leak() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        public_host = request.url.host == "cdn.example"
        return httpx.Response(200 if public_host and PROBE_KEY in request.url.path else 403)

    report = check_bucket(
        target(FakeWriter(), ("http://storage:9000", "https://cdn.example")),
        httpx.Client(transport=httpx.MockTransport(handle)),
    )

    assert {request.url.host for request in seen} == {"storage", "cdn.example"}
    assert report.public == ["https://cdn.example: anonymous read of the probe answered 200"]


def test_a_policy_the_provider_reports_public_fails_even_when_requests_are_refused() -> None:
    writer = FakeWriter(policy={"PolicyStatus": {"IsPublic": True}})

    report = check_bucket(target(writer), answering())

    assert report.public == ["the provider reports the bucket policy as public"]
    assert report.policy == "public"


def test_a_provider_without_policy_status_is_recorded_not_failed() -> None:
    writer = FakeWriter(policy=client_error("NotImplemented"))

    report = check_bucket(target(writer), answering())

    assert report.public == []
    assert report.errors == []
    assert report.policy == "unsupported (NotImplemented)"


def test_a_private_policy_status_is_recorded() -> None:
    writer = FakeWriter(policy={"PolicyStatus": {"IsPublic": False}})

    assert check_bucket(target(writer), answering()).policy == "not public"


def test_no_bucket_policy_at_all_is_not_public() -> None:
    assert check_bucket(target(FakeWriter()), answering()).policy == "no bucket policy"


@pytest.mark.parametrize("status", [404, 500, 503])
def test_an_unexpected_answer_is_an_error_not_a_pass(status: int) -> None:
    report = check_bucket(target(FakeWriter()), answering(list_status=status))

    assert report.public == []
    assert report.errors == [f"https://s3.example: anonymous list answered {status}"]
    assert exit_code([report]) == 2


def test_an_unreachable_endpoint_is_an_error_and_the_probe_is_still_removed() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    writer = FakeWriter()
    report = check_bucket(target(writer), httpx.Client(transport=httpx.MockTransport(refuse)))

    assert report.errors == [
        "https://s3.example: anonymous list failed: ConnectError",
        "https://s3.example: anonymous read of the probe failed: ConnectError",
    ]
    assert writer.calls[-1] == ("delete", PROBE_KEY)


def test_a_probe_that_cannot_be_written_is_an_error() -> None:
    class ReadOnly(FakeWriter):
        def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> object:
            raise client_error("AccessDenied")

    writer = ReadOnly()
    report = check_bucket(target(writer), answering())

    assert report.errors == ["could not write the probe object: AccessDenied"]
    assert writer.calls == []


def report(public: list[str] | None = None, errors: list[str] | None = None) -> BucketReport:
    return BucketReport("media", "b", public or [], errors or [], "no bucket policy")


@pytest.mark.parametrize(
    ("reports", "code"),
    [
        ([report()], 0),
        ([report(), report(public=["x"])], 1),
        ([report(errors=["x"])], 2),
        ([report(public=["x"]), report(errors=["y"])], 1),
        ([], 2),
    ],
)
def test_exit_code_is_1_for_public_2_for_errors_and_never_0_without_a_check(
    reports: list[BucketReport], code: int
) -> None:
    assert exit_code(reports) == code


def test_locally_only_the_media_bucket_is_checked_on_both_endpoints() -> None:
    found = targets(
        Settings(
            s3_endpoint_url="http://storage:9000", s3_public_endpoint_url="http://localhost:9000"
        )
    )

    assert [(t.label, t.bucket, t.endpoints) for t in found] == [
        ("media", "listenup", ("http://storage:9000", "http://localhost:9000"))
    ]


def test_production_checks_the_backup_bucket_with_its_own_endpoint() -> None:
    found = targets(
        Settings(
            **PRODUCTION,
            s3_bucket="media",
            s3_endpoint_url="https://s3.example",
            backup_bucket="dumps",
            backup_s3_endpoint_url="https://backup.example",
            backup_s3_access_key="backup-key",
            backup_s3_secret_key=SecretStr("backup-secret"),
        )
    )

    assert [(t.label, t.bucket, t.endpoints) for t in found] == [
        ("media", "media", ("https://s3.example",)),
        ("backup", "dumps", ("https://backup.example",)),
    ]


def test_main_prints_one_json_line_per_bucket(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from listenup.ops import storage_check

    monkeypatch.setattr(
        storage_check,
        "targets",
        lambda settings: [target(FakeWriter())],
    )
    make_http: Callable[[], httpx.Client] = lambda: answering(get_status=200)  # noqa: E731
    monkeypatch.setattr(storage_check, "_http_client", make_http)

    assert storage_check.main([]) == 1
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines == [
        {
            "label": "media",
            "bucket": "listenup-media",
            "public": ["https://s3.example: anonymous read of the probe answered 200"],
            "errors": [],
            "policy": "no bucket policy",
        }
    ]
