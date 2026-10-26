"""The edge's Caddyfile keeps its caching and streaming rules (#112, ADR 0065).

These read the file as text; the image build runs `caddy validate`, and the review
fixes were checked against a running Caddy (docs/runbooks/deploy.md, rehearsal).
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
CADDYFILE = (REPO / "infra/caddy/Caddyfile").read_text()


def _block(opening: str) -> str:
    start = CADDYFILE.index(opening)
    depth = 0
    for index in range(start, len(CADDYFILE)):
        depth += {"{": 1, "}": -1}.get(CADDYFILE[index], 0)
        if CADDYFILE[index] == "}" and depth == 0:
            return CADDYFILE[start : index + 1]
    raise AssertionError(f"unclosed block {opening!r}")


def test_only_assets_that_exist_are_cached_as_immutable() -> None:
    # A 404 marked immutable would sit in browsers and any CDN for a year.
    assets = _block("handle /assets/* {")
    assert re.search(r"@exists file\b", assets)
    assert re.search(r'header @exists Cache-Control "public, max-age=31536000, immutable"', assets)
    assert not re.search(r"^\s*header Cache-Control", assets, re.MULTILINE)


def test_the_event_stream_is_never_compressed() -> None:
    # Compression can hold back events until a buffer fills; the stream stays plain
    # whatever the Caddy version's defaults.
    assert re.search(r"@compressible not path /api/v1/events\b", CADDYFILE)
    assert re.search(r"^\s*encode @compressible zstd gzip$", CADDYFILE, re.MULTILINE)
    assert not re.search(r"^\s*encode zstd gzip$", CADDYFILE, re.MULTILINE)


def test_client_addresses_are_never_taken_from_request_headers() -> None:
    # Without trusted_proxies Caddy replaces any client-sent X-Forwarded-For.
    assert "trusted_proxies" not in CADDYFILE
