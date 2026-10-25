"""Seed a migrated database for the B5 load test (#94) and write the k6 manifest.

Run from apps/api as the database owner; the B5 runner (spikes, `spike-b5`) calls it:

    uv run python scripts/seed_load.py --learners 150 --history 10 \\
        --blind-learners 20 --blind-sessions 8 --out /path/to/manifest.json

Each learner gets the fixture script's clip and sessions at every step, including an
active Blind attempt (tests/integration/seed.py), a cached transcript, `--history`
extra clips with their sessions, and a login session whose token goes in the
manifest. The first `--blind-learners` learners also get `--blind-sessions` fresh
sessions open at Blind for the heartbeat load. The manifest holds session tokens:
never commit it.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from listenup.platform.config import get_settings
from tests.integration.load_seed import seed_load


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--learners", type=int, default=150)
    parser.add_argument("--history", type=int, default=10, help="extra clips per learner")
    parser.add_argument("--blind-learners", type=int, default=20)
    parser.add_argument("--blind-sessions", type=int, default=8)
    parser.add_argument("--database-url", default=get_settings().database_url)
    parser.add_argument("--secure-cookies", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.blind_learners > args.learners:
        parser.error("--blind-learners cannot exceed --learners")

    started = time.monotonic()
    manifest = seed_load(
        args.database_url,
        learners=args.learners,
        history=args.history,
        blind_learners=args.blind_learners,
        blind_sessions=args.blind_sessions,
        secure_cookies=args.secure_cookies,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest) + "\n")
    args.out.chmod(0o600)
    print(
        f"seeded {args.learners} learners ({args.blind_learners} with Blind sessions) "
        f"in {time.monotonic() - started:.0f} s; manifest {args.out}"
    )


if __name__ == "__main__":
    main()
