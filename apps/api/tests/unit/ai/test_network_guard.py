import httpx
import pytest


@pytest.mark.anyio
async def test_a_real_request_is_refused_in_ai_tests():
    async with httpx.AsyncClient() as client:
        with pytest.raises(Exception):  # noqa: B017  (httpx wraps the refusal)
            await client.get("http://example.invalid/")
