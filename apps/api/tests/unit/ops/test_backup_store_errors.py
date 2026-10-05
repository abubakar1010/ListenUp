"""The S3 backup store: refused deletes, its bucket and its credentials (#97, ADR 0032)."""

from typing import Any

import pytest
from pydantic import SecretStr

from listenup.ops.store import S3BackupStore
from listenup.platform.config import Settings


class FakeClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response

    def delete_objects(self, **_: Any) -> dict[str, Any]:
        return self.response


def store_with(response: dict[str, Any]) -> S3BackupStore:
    store = S3BackupStore(Settings())
    store._client = FakeClient(response)  # type: ignore[assignment]
    return store


def test_a_delete_the_bucket_refuses_for_a_key_is_an_error() -> None:
    store = store_with({"Errors": [{"Key": "backups/old/listenup.dump", "Code": "AccessDenied"}]})

    with pytest.raises(RuntimeError, match=r"backups/old/listenup\.dump \(AccessDenied\)"):
        store.delete(["backups/old/listenup.dump"])


def test_a_delete_without_errors_succeeds() -> None:
    store_with({"Deleted": [{"Key": "backups/old/listenup.dump"}]}).delete(
        ["backups/old/listenup.dump"]
    )


def test_production_refuses_a_missing_or_shared_backup_bucket() -> None:
    for backup_bucket in (None, "listenup"):
        with pytest.raises(ValueError, match="separate from the media bucket"):
            S3BackupStore(Settings(environment="production", backup_bucket=backup_bucket))


def test_production_accepts_a_separate_backup_bucket() -> None:
    store = S3BackupStore(Settings(environment="production", backup_bucket="listenup-backups"))

    assert store.bucket == "listenup-backups"


def test_local_runs_fall_back_to_the_media_bucket() -> None:
    assert S3BackupStore(Settings(environment="local")).bucket == "listenup"
    assert S3BackupStore(Settings(environment="test", backup_bucket="other")).bucket == "other"


def test_backup_credentials_and_endpoint_replace_the_apis() -> None:
    store = S3BackupStore(
        Settings(
            backup_s3_endpoint_url="https://backups.example.com",
            backup_s3_region="eu-west-1",
            backup_s3_access_key="backup-key",
            backup_s3_secret_key=SecretStr("backup-secret"),
        )
    )

    client = store._client
    credentials = client._request_signer._credentials  # type: ignore[attr-defined]
    assert client.meta.endpoint_url == "https://backups.example.com"
    assert client.meta.region_name == "eu-west-1"
    assert credentials.access_key == "backup-key"
    assert credentials.secret_key == "backup-secret"


def test_without_backup_credentials_the_apis_are_used() -> None:
    store = S3BackupStore(Settings(s3_access_key="api-key"))

    credentials = store._client._request_signer._credentials  # type: ignore[attr-defined]
    assert credentials.access_key == "api-key"
