# Media worker sandbox and scanner

See [ADR 0049](../adr/0049-media-worker-sandbox-and-upload-scanning.md).
Requires Docker Engine 28+ (isolated bridge gateway mode) and Compose 2.24+.

`docker compose up --build` provisions models once through `media-models` and
starts `media-signatures` (freshclam), then starts the restricted worker after
both are ready. Model downloads need public network access only in the provisioner.
Signatures persist in `clamav-signatures`; jobs mount them read-only. The updater
checks 12 times a day. Never replace the full production databases with the tiny
test database used in the contract check. If migrating an existing dev stack,
recreate DB/storage containers so they join the new network; keep their volumes.

For signature failures, inspect `docker compose logs media-signatures` and its
health. Fix network/mirror/disk permission problems in the updater, not by adding
network access or writable signature storage to jobs. ClamAV refuses missing or
more-than-seven-day-old CVD databases. An unreadable/unscannable upload becomes
`upload_unreadable`; a detected file becomes `upload_infected`. Both originals
are deleted and processing stops. The existing failed-content response supplies
the refusal text; ask the learner to upload a clean copy after scanning works.

The whole media worker has a read-only root, no capabilities, no host gateway,
and only scratch tmpfs writes. Its network reaches only DB/storage. Don't add
API, telemetry collectors, mail, model downloaders, proxies or a Docker socket to
this boundary. Future media jobs automatically inherit it; this does not enable
YouTube intake or build #38.

Docker's `/dev/shm` and `/dev/mqueue` mounts are explicitly read-only as well.
Job launchers remain child subreapers, retaining CPU consumed by orphaned exits.
SIGCHLD disposition changes are denied to prevent auto-reaping from discarding CPU
accounting. A library that requires a custom SIGCHLD handler must be validated
before enabling it; do not weaken the filter to resolve a startup error.

With `LISTENUP_OTEL_ENABLED=true`, media supervisors and child jobs queue bounded,
content-free OTLP batches through PostgreSQL. The default/background worker handles
`platform.export_media_telemetry` and delivers to its configured collector endpoints
with bounded retries. Enable telemetry and set endpoints on both pools; collector
credentials belong only to the default pool. Inspect failed relay jobs when signals
are missing. No media-to-collector network route is required. A killed child's last
buffered signals can be lost, while its supervisor still records the failed job.

Each job has an isolated process session and temporary scratch directory.
Defaults: 8 GiB memory/address-space, 600 CPU seconds, lane-specific wall time
(intake: 10 minutes; speech-interactive: 3 minutes). Configure memory/CPU with
`LISTENUP_MEDIA_JOB_MEMORY_MB` and `LISTENUP_MEDIA_JOB_CPU_SECONDS`; update Compose
container memory/CPU/pids ceilings consistently with the number of slots.
Oversized jobs are killed, marked failed immediately and release their intake
slot. Operator/manual retries remain an explicit decision. Transient service
failures still use the normal bounded retry policy.

For fast reproducible Docker validation, run from the repository root on a local
or disposable stack with ports 5432, 9000 and 8000 available:

```sh
docker build -f infra/docker/backend.Dockerfile --target media-runtime -t listenup-media-check .
python infra/scripts/check-media-sandbox.py listenup-media-check
```

Use the actual worker-media image as the argument to check its image as well.
A second argument can select a small Python canary image to reduce Docker disk
usage while checking the full media image.
The check uses the deployed Compose service restrictions, starts DB/storage and
a canary on the API network/published port, and asserts filesystem, network,
ClamAV and real CPU/memory/time enforcement. It removes its canary, test worker
and temporary hash database; local DB/storage remain running. A managed builder
may need the optional `proxy_ca` build secret from its runtime certificate bundle.

CI runs this small runtime check without speech weights or signature downloads;
normal image CI still builds the complete speech image. Real model loading and
signature mirror availability are deployment readiness checks, not simulated by
the tiny EICAR fixture. Speech latency after process isolation is unverified until
measured on staging under [#155](https://github.com/abubakar1010/ListenUp/issues/155).
