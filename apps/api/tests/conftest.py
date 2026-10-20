import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def clean_upload_scanner():
    """Existing caller tests have a clean scanner; adapter tests exercise ClamAV."""
    from listenup.modules.content.scanner import use_scanner

    class Clean:
        async def scan(self, source):
            pass

    use_scanner(Clean())
    yield
    use_scanner(None)
