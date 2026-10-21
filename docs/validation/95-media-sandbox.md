# Story #95 validation

Branch: `feat/95-sandbox-media-worker`, from current `origin/main` at `4efc101`.
Issue: [#95](https://github.com/abubakar1010/ListenUp/issues/95).
Decision: [ADR 0049](../adr/0049-media-worker-sandbox-and-upload-scanning.md).
Operations: [runbook](../runbooks/media-sandbox.md).

The owner explicitly requested no plan and excluded YouTube #38 implementation.
Claude Code was not installed; work continued with Codex under the shared rules.
No changes to review, identity, grading, AI adapters, or web code. The existing
content failure response provides the upload refusal text; no schema/route/client
change or migration is needed.

## Acceptance criteria and actual test-first evidence

Commands below run in `apps/api` unless they start with `python infra/`.
Environment/setup failures are listed separately and are not counted as Red.

| Requirement / result | Named evidence | Actual Red before implementation | Green / refactor |
| --- | --- | --- | --- |
| NFR-SEC-3: clean only on scanner exit 0; infection/error stable ProblemError codes | `test_clamav_refuses_infected_or_unreadable_files`, `test_clamav_accepts_only_success` | `uv run pytest tests/unit/test_upload_scanner.py -q`: missing public `scanner` interface, collection error | Same command: initial 3 passed; final expanded scanner suite 8 passed |
| EICAR/scanner refusal deletes original, persists failed upload/media, raises PermanentError, never probes | `test_scanner_refusal_deletes_original_and_fails_before_probe` (infected and unreadable), Docker `check_scanner` | `LISTENUP_REQUIRE_DB=1 uv run pytest tests/integration/test_conversion.py -k scanner_refusal -q`: 2 failed with `AssertionError: must scan before parsing` | Same command: 2 passed; later both plus real process settlement: 5 passed |
| Non-root, read-only except scratch, no API route, storage/DB reachable | `test_media_compose_has_readonly_root_and_isolated_network`, Docker `check_filesystem` / `check_network` | `uv run pytest tests/unit/test_media_infra.py -q`: failed `KeyError: read_only` against old Compose | 1 passed; live Docker probes pass on media-runtime and complete worker-media image |
| Per-job time, memory and CPU kill; whole group stays bounded | `test_sandbox_kills_jobs_over_time_memory_or_cpu`, `test_memory_budget_covers_descendants_together`, `test_cpu_budget_covers_descendants_together`, `test_sandbox_disallows_detaching_children`, `test_cancellation_kills_descendants`, `test_pool_enables_process_isolation_before_accepting_jobs` | `uv run pytest tests/unit/test_media_sandbox.py -q`: missing public sandbox interface. After initial implementation: aggregate-memory case failed with wall-time error instead of memory error | Initial 4 then 6 passed after aggregate budget/runner wiring; final focused sandbox/child/scanner/infra suites: 33 passed |
| Limit kills mark job and upload failed on first attempt, not an endless retry | `test_media_process_failure_settles_job_on_first_attempt`, `test_over_budget_process_fails_queue_job_and_upload_on_first_attempt` (time, memory, CPU) | Unit settlement case failed because runtime lacked `isolate_media`; observed before wiring runner | Real processes, Procrastinate worker and PostgreSQL: 3 parameter cases pass; each asserts queue `('failed', 1)` and upload's linked media `failed` |
| Transient failures retain retries and final settlement | `test_child_transient_errors_still_use_job_retries`, `test_transient_child_failure_settles_only_after_last_attempt` | Focused `-k transient`: PermanentError wrongly returned for exit 75. Focused `-k settles_only`: final hook await count 0 instead of 1 | Expanded sandbox suite passes, including first-attempt permanent settlement and last-attempt transient settlement |
| SIGKILL cannot leave a job's scratch files behind | `test_job_scratch_is_removed_after_a_killed_job` | Focused `-k scratch`: failed `KeyError: env` because no per-job scratch isolation existed | Same command: 1 passed; all cleanup occurs in supervisor's TemporaryDirectory |
| Scanner size limits never silently accept partial scans | `test_scan_limits_are_refusals_not_silent_partial_scans`, Docker `check_scanner` forced-size case | Focused `-k scan_limits`: failed on missing `max_file_bytes` public option | Expanded scanner suite: 8 passed; actual ClamAV size-limit case refuses |
| NFR-SEC-2 and existing type/size/ffmpeg re-encode behavior preserved | Existing cross-learner, upload, conversion and storage integration tests, including `test_an_mp3_becomes_a_playable_aac_file_with_peaks` | Existing behavior: characterization, not claimed as new Red | Included in required final backend run |

Additional missing-tool, cancellation/reaping, seccomp load failure, child error
classification and request-correlation examples were added as boundary validation
around those cycles. They are not claimed as independently observed Red cycles.
The real scanner's hash-only fixture initially refused even its clean file because
production requires fresh CVD metadata. The contract now independently asserts that
refusal and tests engine decisions using a test instance with only CVD age disabled;
production defaults remain fail closed.

## Assertion quality

Moving scanning after probing fails the integration spy; accepting scanner exit 1
or 2 fails the stable-code tests. Omitting original deletion or failure persistence
fails storage/GET assertions. Removing root read-only/network isolation fails the
Compose contract and live write/API-IP probes. Dropping SIGKILL or detachment
restriction fails real process/descendant tests; losing permanent classification
or the failure hook fails persisted queue status and first-attempt assertions.
No coverage exclusions or thresholds were weakened.

## Final validation

- `uv run ruff format --check .` and `uv run ruff check .`: pass. Infra scripts
  also pass lint/format; Compose and CI YAML parse successfully.
- `uv run mypy`: pass (153 source files); `uv run lint-imports`: all 6 contracts kept.
- Required coverage command with `LISTENUP_REQUIRE_DB=1`, `LISTENUP_REQUIRE_S3=1`,
  `LISTENUP_S3_ENDPOINT_URL=http://localhost:9001` and the scratch PostgreSQL 16
  tools on PATH: **1374 passed, 3 failed, 1 performance test deselected**, 419.46 s.
  All three failures were host disk exhaustion during a repeated large-image
  probe (PostgreSQL CREATE DATABASE, S3 backup upload, S3 range playback).
  After deleting only disposable task images/cache, the exact three failed tests
  passed with `--cov --cov-append` (3 passed, 9.92 s). This is a repaired focused
  rerun, not a claim that the original full command exited green. Required CI
  must supply a clean full-suite run before merge.
- New scanner/process/child/infra focused suites: 33 passed. The worker-module suite
  additionally passes all 4 tests, including both media/default readiness cases,
  with coverage appended.
- `uv run pytest -m performance --no-cov -q`: 1 passed (2.29 s).
- Runtime coverage inventory gate passes. Changed executable lines: at least 97%
  against `origin/main`, above the 90% minimum. Scanner and runner changes have
  complete changed-line coverage. The readiness tests cover the pool isolation
  switch; remaining uncovered lines are two process-disappearance race handlers
  and the two Python module `__main__` launch lines (exercised by Docker outside
  pytest coverage). No source exclusions were added.
- Docker sandbox check: all filesystem, network, real ClamAV and real process-limit
  groups pass. Both runtime and complete speech image were checked. The final
  runtime check also validates a live API network alias/published port and the
  scanner's forced-size refusal. Repeated full-image checks hit the managed
  container's 32 GiB Docker/VFS disk ceiling; the script accepts an optional small
  canary image, and CI uses the lightweight runtime for both containers.
- No schema, route, generated client, or web changes: migration round-trip and web
  authoring checks are not applicable to this diff. Existing migration/security,
  storage and cross-learner tests were included in the broad backend run.

## Environment observations and Docker applicability

Docker Engine 28.4.0 was available. Both media-runtime and the full worker-media
image built; both passed the live filesystem/network/scanner/process checks. The
signature-update image also builds and its installed ClamAV reports version 1.4.3.
The full media image is approximately 3.45 GB uncompressed, dominated by the existing
speech dependencies; the lightweight contract image is approximately 0.99 GB.
Signatures and speech weights are absent from these image layers.

Initial DB-unavailable setup was repaired before the actual scanner integration
Red. The first coverage suite reported 1365 passed, seven missing-pg-client setup
errors and one accounting failure against the default DB at migration 0012. The
matching PostgreSQL 16 tools were extracted into ignored scratch space, and the
local default DB was migrated to head. Backup rerun: 7 passed; transcript-audio
rerun: 2 passed. A final full suite is run with both services required.

The existing local SeaweedFS volume had a stale raft configuration and could not
serve S3 requests. Its data was preserved. Full S3 tests use a separate fresh local
SeaweedFS instance on :9001; the Docker isolation probe uses the Compose service.

No Docker-only sandbox acceptance check is blocked in this container. Production
signature mirror refresh and actual speech-model provisioning/inference are not
simulated by the offline engine fixture; they remain deployment readiness checks.
Actual speech latency/capacity after per-job process isolation is **deferred until
staging — unverified** under [#155](https://github.com/abubakar1010/ListenUp/issues/155),
with the existing System Design targets unchanged. Required CI and a fresh-session
independent review remain owner merge gates. No helper agents were used.


## CI network-listener regression

The initial push workflow passed completely, including the full backend suite;
PR backend and changed-coverage jobs also passed. The PR sandbox job exposed a
positive-access failure: storage TCP connection refused. Readiness was initially
suspected. A live reproduction showed SeaweedFS listening on loopback and the
default-network IP only, with no listener on its media-network IP. Its automatic
bind-address selection depends on which interface it chooses.

`test_storage_listens_on_the_media_interface_as_well_as_default` was observed
failing before adding `-s3.ip.bind=0.0.0.0`; the live Docker network probe also
failed before the change. S3 now listens on both permitted interfaces. The extra
`test_internal_services_wait_for_tcp_before_media_can_start` was also observed
red before strengthening PostgreSQL/S3 TCP health checks. These prevent readiness
from relying on a temporary Unix-only init server or cluster health alone. API
isolation and network membership are unchanged.

After the fix: configuration suite 3 passed, live Docker probe all groups passed,
and the real S3 adapter contract against the Compose storage service 3 passed.
The fix is a listener binding/readiness change, not a retry of a failed assertion.

## PR #172 review remediation

The owner approved the remediation plan, upload-only dependency exception, and
DB/storage design clarification. #38 remains unimplemented and outside scope.

- CPU regression: `uv run pytest tests/unit/test_media_sandbox.py -k retains_auto
  --no-cov -q` observed **1 failed, 1 passed** before the fix. The auto-reaped
  case completed above its 1-second CPU budget. The orphan case characterized
  this host's unreaped zombies; the expanded live Docker check also exercises
  orphan reaping under container init. A job-local Linux subreaper now retains
  waited/orphaned CPU, and seccomp denies SIGCHLD disposition changes that could
  enable SIG_IGN/SA_NOCLDWAIT. Tests cover bounded work, transient/permanent status,
  failed subreaper setup, leftover termination and disappearing-process races.
- Filesystem regression: the expanded real Docker probe first failed with
  `write outside scratch succeeded: /dev/shm`. Explicit read-only `/dev/shm` and
  `/dev/mqueue` mounts then passed the probe. Root read-only alone was insufficient.
- Telemetry regression: `uv run pytest tests/unit/test_media_telemetry.py --no-cov
  -q` first failed both cases on the missing relay boundary. Queued OTLP exporters
  now preserve metrics/traces and child trace ancestry through PostgreSQL, with
  delivery by the default pool. Unit cases validate protobuf encoding, bounded
  payloads, disabled signals, redacted failures and HTTP retries; the PostgreSQL
  test asserts the persisted background job and its delivery payload. No schema,
  collector route, or media privilege was added.
- Final focused boundary suites: **57 passed**. Scanner refusal and real-budget
  settlement integration cases: **5 passed**. Real persisted relay integration:
  **1 passed**. Lint, formatting, strict mypy (154 files) and six import contracts
  pass. Added defensive cases beyond the observed regressions are supplemental
  validation rather than separately claimed test-first cycles.
- Both media runtime and complete speech images build. Actual provisioner code
  downloaded and loaded configured `small.en` and `WAV2VEC2_ASR_BASE_960H` models.
  A new interpreter inside the deployed non-root/read-only/network-isolated
  Compose service then performed real offline transcription (**29 words**) and
  alignment (**28 words**) on the public Narsil/asr_dummy `1.flac` fixture, inside
  an 8 GiB/600 CPU-second/180-second job boundary. It completed in **28.66 s**.
  This proves functional provisioning/inference, not model quality or staging
  latency/capacity; those existing targets remain unchanged under #155.
- The real freshclam updater downloaded/verified daily, main and bytecode CVDs
  using the session proxy/CA. A read-only consumer using production freshness
  defaults accepted the public audio and rejected EICAR as `upload_infected`.
  No freshness override was used for this production-database check.
- Concurrent large-image runs exhausted this managed environment's Docker/VFS
  disk. Disposable build images/cache and verified unreferenced copies abandoned
  by failed container creation were removed, retaining DB/storage/model volumes.
  The image builds and provisioning checks above subsequently completed.
- The complete required-service backend coverage command completed with **1398
  passed, 1 failed, 1 performance test deselected** in 425.10 s. The one failure
  was the existing real-storage/configured-gateway transcript test: its accounting
  connection used the default local database, still at migration **0012**. After
  `uv run alembic upgrade head` on that local database, the exact failed test,
  neighboring decode case and expanded telemetry boundaries passed with coverage
  appended: **11 passed**. This is a repaired focused rerun, not a claim that the
  original full command exited green. Required CI remains the clean full-suite
  merge gate. `uv run pytest -m performance --no-cov -q`: **1 passed**, 2.95 s.
- Runtime coverage inventory passes. Changed executable coverage against base
  `4efc101` is **98%**; no thresholds or exclusions changed. Remaining uncovered
  lines are the child-CPU exit-code race, disappearing `/proc` races and module
  launch lines; real process/Docker checks exercise those boundaries separately.
- Final live Docker contract passes on the **complete speech image**, with the
  runtime image as the small API canary: non-root/read-only including auxiliary
  mounts, writable scratch, API DNS/IP/host-gateway denial, DB/storage access,
  real ClamAV outcomes, actual ClamAV/ffmpeg/ffprobe under the job signal filter,
  CPU/memory/wall kills, and retained CPU for auto-reaped/orphaned descendants.
- Code remediation commit: `cd4d0c5`. CI run **39658730602** was queued/running
  at handoff; no green result is claimed here. This documentation follow-up also
  requires current CI before owner merge. Independent re-review of the new
  supervision/telemetry changes remains required; no helper agents were used.
