"""Docker contract check of the deployed Compose sandbox. Run from any directory.

Build media-runtime (quick; no speech weights/signature downloads), then:
  python infra/scripts/check-media-sandbox.py listenup-media-check:95
An actual worker-media image may be supplied instead. A second image argument
can provide a lightweight Python canary when local Docker disk space is limited. Requires Docker >=28 and
Compose >=2.24. Uses the local dev DB/storage; never runs migrations or models.
"""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def call(command: list[str], **kwargs: object) -> str:
    return subprocess.check_output(command, text=True, **kwargs).strip()


def main() -> None:
    image = sys.argv[1]
    canary_image = sys.argv[2] if len(sys.argv) > 2 else image
    name = f"listenup-api-canary-{uuid.uuid4().hex[:10]}"
    (ROOT / "work").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="sandbox-check-", dir=ROOT / "work"
    ) as directory:
        scratch = Path(directory)
        signatures = scratch / "signatures"
        signatures.mkdir()
        signatures.chmod(0o755)
        checks = scratch / "checks"
        checks.mkdir()
        checks.chmod(0o755)
        shutil.copyfile(
            ROOT / "infra/scripts/media-sandbox-probe.py", checks / "probe.py"
        )
        (checks / "probe.py").chmod(0o644)
        source = scratch / "src"
        shutil.copytree(ROOT / "apps/api/src", source)
        for path in [source, *source.rglob("*")]:
            path.chmod(0o755 if path.is_dir() else 0o644)
        eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
        # Tiny test-only hash database. Real production always uses freshclam's full
        # databases. This exercises the real ClamAV engine without a CDN dependency.
        (signatures / "test.hdb").write_text(
            f"{hashlib.md5(eicar, usedforsecurity=False).hexdigest()}:{len(eicar)}:Eicar-Test\n"
        )
        (signatures / "test.hdb").chmod(0o644)
        override = scratch / "override.json"
        override.write_text(
            json.dumps(
                {
                    "services": {
                        "api": {"image": canary_image},
                        "worker-media": {
                            "image": image,
                            "volumes": [
                                f"{checks}:/checks:ro",
                                f"{source}:/app/src:ro",
                                f"{signatures}:/signatures:ro",
                            ],
                        },
                    }
                }
            )
        )
        compose = [
            "docker",
            "compose",
            "-f",
            str(ROOT / "infra/compose/compose.yml"),
            "-f",
            str(override),
            "--project-name",
            "listenup",
        ]
        try:
            subprocess.run(
                [*compose, "up", "-d", "--wait", "postgres", "storage"], check=True
            )
            call(
                [
                    *compose,
                    "run",
                    "-d",
                    "--no-deps",
                    "--service-ports",
                    "--use-aliases",
                    "--name",
                    name,
                    "--entrypoint",
                    "python",
                    "api",
                    "-m",
                    "http.server",
                    "8000",
                ]
            )
            for attempt in range(30):
                result = subprocess.run(
                    [
                        "docker",
                        "exec",
                        name,
                        "python",
                        "-c",
                        'import socket; socket.create_connection(("api",8000),1).close()',
                    ],
                    capture_output=True,
                    check=False,
                )
                if result.returncode == 0:
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("API canary did not start")
            inspected = json.loads(call(["docker", "inspect", name]))[0]
            addresses = []
            for network in inspected["NetworkSettings"]["Networks"].values():
                addresses.extend([network["IPAddress"], network["Gateway"]])
            subprocess.run(
                [
                    *compose,
                    "run",
                    "-T",
                    "--rm",
                    "--no-deps",
                    "-e",
                    f"SANDBOX_API_ADDRESSES={json.dumps(addresses)}",
                    "--entrypoint",
                    "python",
                    "worker-media",
                    "/checks/probe.py",
                ],
                check=True,
            )
        finally:
            subprocess.run(
                ["docker", "rm", "-f", name], capture_output=True, check=False
            )


if __name__ == "__main__":
    main()
