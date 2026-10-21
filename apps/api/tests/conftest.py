import os

import pytest

# A distinct consent label per document (#104, ADR 0048): with one shared default, a
# check that compared against the wrong kind's version would still pass. Set before
# any test builds Settings; a test that needs other labels passes them explicitly.
os.environ.setdefault("LISTENUP_TERMS_VERSION", "terms-1")
os.environ.setdefault("LISTENUP_PRIVACY_VERSION", "privacy-1")
os.environ.setdefault("LISTENUP_VOICE_CONSENT_VERSION", "voice-1")


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
