import pytest

from listenup.ai import gateway
from tests.unit.ai.accounting_fake import FakeAccounting


@pytest.fixture(autouse=True)
def fake_accounting(monkeypatch):
    store = FakeAccounting()
    monkeypatch.setattr(gateway, "get_accounting", lambda: store, raising=False)
    return store
