"""Exact repository paths that opt CI into the offline smoke subset."""

import sys
from collections.abc import Iterable

AI_ROOT = "apps/api/src/listenup/ai/"


def needs_smoke(paths: Iterable[str]) -> bool:
    return any(
        path == AI_ROOT + "ai.yaml"
        or path.startswith((AI_ROOT + "prompts/", AI_ROOT + "providers/"))
        for path in paths
    )


if __name__ == "__main__":
    paths = sys.stdin.buffer.read().decode("utf-8", errors="surrogateescape").split("\0")
    print("true" if needs_smoke(paths) else "false")
