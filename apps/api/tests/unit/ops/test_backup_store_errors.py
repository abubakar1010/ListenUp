"""The S3 backup store reports keys the bucket refused to delete (#97, ADR 0032)."""

from typing import Any

import pytest

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
