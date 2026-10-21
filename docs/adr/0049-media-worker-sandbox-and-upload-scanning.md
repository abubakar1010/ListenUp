# ADR 0049: Media worker isolation and upload scanning

- Status: Accepted
- Date: 2026-10-20
- Story: #95
- Requirements: NFR-SEC-2, NFR-SEC-3; Architecture 12.1

## Context

Uploads reach native media parsers. Coroutine cancellation cannot enforce a
memory/CPU budget or stop arbitrary synchronous/native work. Container limits
shared by two concurrent jobs are not sufficient per-job limits. YouTube #38 is
not implemented; future media jobs must inherit the same boundary automatically.
The owner approved upload-only completion of #95 without #38 during PR #172
review remediation, together with Architecture 12.1's DB/storage exception.

## Decision

Use **ClamAV**, a free open-source antivirus engine (GPLv2), through the content
module's `Scanner` protocol. `ClamAV.scan` accepts only exit 0, maps exit 1 to
422 `upload_infected`, and maps unreadable files, missing/unusable databases and
other scanner errors to 422 `upload_unreadable` (ProblemError). No parser or
fingerprint deduplication runs before scanning. A refusal stores the media/upload
failure, deletes the original, and raises `PermanentError`; cleanup retries also
remove an original left after storage failure. Uploads have no separate status
column: their linked media object's status/error is the existing source of truth.
Every accepted upload still goes through the existing ffmpeg re-encode path.

Install the engine only in media images. A separate freshclam service maintains a
named signature volume; jobs mount it read-only. Production refuses databases
older than seven days. Keep signatures out of image layers and image builds.
Unit tests use a scanner fake. The Docker contract uses the real engine and a tiny
EICAR hash database: it explicitly proves the production age check refuses a
hash-only database, then disables only that age check on the test scanner instance
to exercise clean/infected/unreadable engine outcomes. There is no environment or
API option to disable production signature freshness. CI needs no signature CDN
or model download; this avoids hundreds of MB of mutable data per build.

Apply the sandbox to the **whole media service**, not to one converter or job
name. It runs as UID/GID 10001, drops all capabilities, denies privilege escalation,
has a read-only root and source/model/signature mounts, and only a bounded 2 GiB
noexec/nosuid/nodev scratch tmpfs. Docker's auxiliary `/dev/shm` and `/dev/mqueue`
mounts are explicitly read-only; root read-only alone does not restrict them. Speech models are provisioned by a separate
one-shot service before startup. Jobs have no writable model cache or downloader
network. No Docker socket or host network is available.

Require Docker Engine 28+ and an internal bridge with gateway mode `isolated`.
Only media, PostgreSQL and storage join this network; API, mail, default workers
and model/signature download services do not. The bridge has no host gateway or
external route. Explicitly empty proxy variables prevent a host-injected proxy
from bypassing that boundary. A live check exercises API DNS, its actual container
IP and its host gateway/published port, as well as positive DB/storage access.

The media supervisor retains Procrastinate ownership and runs **every job** in a
fresh Linux process session. Hard `RLIMIT_AS` and `RLIMIT_CPU` limits are inherited
by subprocesses. A supervisor samples aggregate process-group RSS/CPU every 50 ms
(including reaped-child CPU), enforcing the same budget across descendants, with
a wall deadline from the job's lane spec. Default limits are 8 GiB address space
and aggregate RSS, 600 CPU seconds, and the existing per-job lane wall deadline.
The container adds a 2-core cap, 18 GiB memory/swap ceiling and 256-process ceiling
for both slots and supervisor. Seccomp denies `setsid` and `setpgid` after session
creation, so descendants cannot escape group termination; missing seccomp fails
closed. The launcher stays alive as a Linux child subreaper: wait4 accounting
retains orphaned descendants inside the monitored group, including clone children
without SIGCHLD. SIGCHLD is reset to default before the inherited filter denies
rt_sigaction(SIGCHLD), preventing SIG_IGN and SA_NOCLDWAIT from discarding exited
children's CPU usage. Libraries requiring custom SIGCHLD handlers are refused;
current Python subprocesses, ffmpeg and real speech adapters are validated. SIGKILL terminates the group on limit, crash or cancellation. The parent
waits for the job reaper, which collects orphaned descendants on normal completion;
the container init reaps leftovers after group SIGKILL. The
supervisor cleans each job's scratch directory even after SIGKILL.

A limit or crash is permanent and invokes the existing `on_give_up` hook on the
first attempt, marking the item failed and releasing its intake slot. A normal
scanner/input refusal is already settled by its handler. Transient child errors
remain retryable and invoke the hook after the final attempt. Child error details
are not printed or transported as exception text; request correlation crosses the
boundary as structured stdin data.

When telemetry is enabled, both supervisor and job interpreters use queued SDK
exporters. Content-free OTLP protobufs (bounded to 1 MiB per batch) are queued via
PostgreSQL to `platform.export_media_telemetry` on the default/background pool.
Only that pool contacts collectors, using its own endpoints and headers. There
is no new schema, proxy, collector route, or Docker socket in the media boundary.
Existing trace context crosses stdin so jobs queued by a child retain ancestry.
Queue retries bound transient export failures; an outage beyond the retry budget
can lose telemetry, as with normal best-effort SDK export. A SIGKILL can also lose
the child's buffered signals, while the surviving supervisor records job failure.

ClamAV's maximum file size follows the upload policy, with a total scan budget
twice that size. `--alert-exceeds-max=yes` makes scan-limit exhaustion a refusal,
so a partial scan never silently admits a file to ffmpeg. The real-engine Docker
check includes a small forced scan-limit case.

## Consequences and limitations

Model files are reused on disk, but a fresh job interpreter loads the model it
needs rather than reusing the supervisor's live Python objects. This is a deliberate
isolation tradeoff against ADR 0028's warm-model optimization; model initialization
counts toward the job's limits. Actual speech-model latency/capacity must be checked
on staging under the existing launch validation tracker #155. This story does not
change providers, model configuration, AI adapters or YouTube behavior.

Aggregate enforcement is sampled, not a delegated per-job cgroup: aggregate usage
can overshoot until the next supervisor scheduling interval; per-process hard
limits and the container cgroup remain backstops. RSS accounting conservatively
counts shared resident pages in each process. Raising a hard limit after launch is
not possible within a child. A limit is a failure, never a silent retry loop.

An engine or signature service outage fails closed; the learner can upload again
after the operator repairs scanning. An upload refusal can be displayed using the
existing server `error_code`/`error_detail` fields; no new web flow is needed.
