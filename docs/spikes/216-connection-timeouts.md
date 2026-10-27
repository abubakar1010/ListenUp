# #216: local connection-timeout verification

This is local synthetic evidence only. The actual stage-0 B5 rerun under
[#94](https://github.com/abubakar1010/ListenUp/issues/94) and
[#155](https://github.com/abubakar1010/ListenUp/issues/155) is
**deferred until staging — unverified**. #216 must remain open for deployed and
stage-0 verification. No infrastructure was provisioned or production deployed.

## Configuration and test-first evidence

Base: current main `c7975df6de4d0903d46a30af4df6d6dd1bee41e5`.
The only existing longer timeout was the historical B5 diagnostic (10 s);
production had neither an explicit API idle timeout nor an explicit Caddy pool
idle lifetime. Normal launch commands now use API 30 s and Caddy uses 15 s.
See the [deploy runbook](../runbooks/deploy.md#http-connection-reuse-216) for
semantics, official references, margins and why the issue's timeout ordering is
reversed for Caddy's HTTP transport.

From the repository root:

```sh
UV_CACHE_DIR=/workspace/.cache/uv uv run --project apps/api pytest apps/api/tests/unit/test_compose_prod.py -k 'keepalive or retires' -q
```

- Red, before changing configuration: **5 failed**, for four missing explicit API
  options and the missing Caddy HTTP transport idle setting. An initial B5 test
  loader error on Compose's `!override` tag was corrected before this recorded red.
- Green: same focused command; the full neighboring file then **29 passed**.
- `test_api_keepalive_has_margin_above_blind_heartbeat` covers production Compose,
  image CMD, development Compose and B5 Compose. It also preserves shutdown grace.
- `test_proxy_retires_idle_connections_before_the_api` covers enabled reuse,
  15 s pool lifetime and absence of new active-response deadlines.
- Configuration behavior changes follow TDD; prose needs no artificial red test.
  No application executable lines, routes, schema, heartbeat logic or Blind rules
  change, so application changed-line coverage/API generation are not applicable.

## Exact remaining stage-0 verification

On the real deployed release candidate, confirm the effective Uvicorn command
contains `--timeout-keep-alive 30` and Caddy's adapted HTTP transport contains
`keep_alive.idle_timeout = 15000000000` (15 s). Record the image digests, tested
commit, effective configuration and any host overrides; check both hops.

Run the existing `spike-b5 --stage0 --skip-up --base-url <deployment>` with its
health URL and database owner URL pointing at that deployment: **150 learners,
10 history clips each, 15 mixed requests/s plus 20 Blind learners at the unchanged
5 s heartbeat interval, 60 s warm-up and 600 s measured**. Use another generator
machine where possible and record the deployment's own CPU. Keep raw request data,
request counts, delivered load, no-response/error codes, attempt outcomes, p95
reads/writes (including failures and answered-only), CPU and slow statements.

Require no heartbeat failures without a response, or enumerate every remaining
one with its cause (#216). Review against the unchanged B5 targets: read p95
<200 ms, write p95 <300 ms and server CPU <30%; retain ADR 0065's proposed error
and delivered-load validity checks and identify their proposal status. Link the
independently reviewed evidence from #94/#155. Local synthetic success cannot
satisfy these criteria or justify closing #216 as fully validated.

## Initial local validation attempt (superseded below)

Tested configuration commit: `fa4d404c1fdc2abda7e45295d00e14ef41e0514d`.
Production Compose resolved with `infra/deploy/env.example` and `LISTENUP_IMAGE_TAG=r1`;
Caddy **2.10.2** `validate --config infra/caddy/Caddyfile --adapter caddyfile`
passed. Uvicorn is pinned at **0.54.0**. The API image built successfully.
`pytest apps/api/tests/unit/test_compose_prod.py apps/api/tests/unit/test_deploy_scripts.py -q`
passed **51 tests**; changed test formatting and Ruff lint passed; `git diff --check`
passed. Full application suites were not run: application code is unchanged.
Fresh-session independent review and required CI remain outstanding.

A reduced B5 comparison was attempted with the existing harness: 25 learners,
1 history clip each, 20 Blind learners, 15 mixed requests/s, 20 s warm-up and
120 s measurement; control API timeout 5 s, intended fixed API timeout 30 s
and proxy pool lifetime 15 s. **No valid new comparison completed: request counts
and failures are unavailable, not zero.** Startup exposed workspace permissions
(non-root migration could not read pyproject.toml; bind-mounted source was not
readable by the image user). Scratch-only root users allowed startup. Then the
harness's fixed `listenup-b5-k6` container name conflicted with an active container.
Automatic approval review rejected the follow-up as potentially interfering with
an active load test on the project/network/database. No workaround was attempted
after that rejection. No counts from that concurrent run are used here. The
real server/proxy reuse experiment also remains unrun; Caddy validation proves
configuration acceptance, not runtime transport reliability.

The historical comparison in [#94's report](94-b5-load-test.md) remains the only
completed B5 comparison: at 15 mixed requests/s plus 20 Blind learners, the 5 s
run had 249 failures out of 2,520 heartbeats; the diagnostic 10 s run had 0 out of
2,512. Those are historical local results, not measurements of this commit or of
the new proxy settings. Repeat the local comparison in a fully disposable stack
with unique ports, project, database and k6 name before treating this PR's local
transport verification as complete.

## Follow-up: isolated runtime verification

The follow-up uses a separate `listenup-216-verify` Compose project, network and
volumes, PostgreSQL at host port 56432, storage at 19000, API at 18001 and Caddy at
18081. k6 is named `listenup-216-verify-k6`. It shares no database or mutable
container state with the earlier project or another session. Local-only root
users compensate for the workspace's source permissions; they are not production
changes. The API/worker use the built `listenup-216-api` image; Caddy is 2.10.2.

### Live connection experiment

A disposable ASGI probe returns its actual TCP peer address. Uvicorn 0.54.0 uses
the 30 s value read from production Compose. Caddy 2.10.2 uses the production
Caddyfile, with only the listener/upstream addresses changed to separate loopback
ports (18083/18082), the media origin replaced, and its admin endpoint disabled.
Forwarded-header processing is disabled only on the probe so the recorded port
is the TCP port rather than the forwarded client port (which Uvicorn sets to 0).

Using one stdlib `http.client.HTTPConnection` with no retry, send a POST, wait
5.2 s and send another, then wait 16 s and send a third. Assert the first two
responses identify the same upstream port and the third identifies a new one.
**Passed: 3 requests, 0 failures**; ports were 33164, 33164, 58952. This verifies
reuse beyond a normal beat and proxy retirement before the API's idle deadline.
It is a synthetic transport check, not an application or stage-0 benchmark.
The first development probe ran before Uvicorn was ready and received 502;
readiness was corrected before this successful experiment. An initial assertion
also exposed forwarded-port rewriting; neither development attempt is counted
as a successful transport experiment.

### Follow-up B5 method and exclusions

The existing JS workload and Python summary logic are unchanged. A scratch
launcher supplies the unique k6 name and excludes only local API/edge addresses
from the outbound HTTP proxy (`NO_PROXY` and `no_proxy` in k6's container).
Without this local exclusion the platform proxy returned 403 even though the
same learner's direct API request succeeded. Those authorization-refused runs
(and an interrupted follow-up) delivered no useful Blind comparison and are
excluded, not combined with the results below.

All accepted modes use 25 learners with one history clip each, 20 concurrent
Blind learners, 15 mixed requests/s, 20 s warm-up and 120 s measured. They use
fresh seeded learners per mode and run sequentially. The control explicitly
sets API idle to 5 s; fixed-direct uses the normal 30 s command; fixed-proxy
uses API 30 s through the committed Caddyfile's 15 s pool lifetime. Fake AI,
PostgreSQL 16 and local storage are used; no media-worker/model load.

The tested HEAD is `7d86961d5c04edf254c7513e1f3c073ffbd41b20`, whose configuration
is identical to `fa4d404c1fdc2abda7e45295d00e14ef41e0514d`. The harness records
`git_dirty=true` because this evidence document was being updated during the
runs; no application, harness or deployment configuration files changed.
The small loopback transport probe overlapped the control's early window;
these runs establish local failure/reuse behavior, not performance qualification
or a controlled latency comparison. Another project's idle services were not
stopped or used. Raw reports and reproduction details are in
[`data/216/`](data/216/README.md). No private manifest or tokens are retained.

Effective fixed container command: `uvicorn listenup.main:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 5 --timeout-keep-alive 30`. Caddy adaptation confirms `keep_alive.idle_timeout=15000000000` ns (15 s); the adapted JSON is retained with the evidence. API and worker image digest: `sha256:2a5cb05240cddc3f7bb17861e7fe665d38b29d65f4cf1e6b761ad5ceec517bd7`.

The first proxy-mode attempt was also excluded: Caddy's inherited outbound proxy
answered `403 Loopback targets forbidden` for its local upstream. The scratch
edge was recreated with `NO_PROXY`/`no_proxy` for `api-via-edge,api,localhost,127.0.0.1`
before the accepted proxy rerun. No production setting was changed for this
managed-environment networking issue.

### Accepted local results

| Mode | Read requests / errors | Write requests / errors (beats included) | Heartbeats / errors | Mixed req/s | Beats/s |
| --- | --- | --- | --- | --- | --- |
| control | 1347 / 0 | 980 / 84 | 520 / 84 | 15.06 | 4.33 |
| fixed-direct | 1338 / 0 | 1009 / 0 | 520 / 0 | 15.22 | 4.33 |
| fixed-proxy | 1332 / 0 | 1000 / 0 | 520 / 0 | 15.10 | 4.33 |

The control's 84 no-response failures were 70 k6 code 1220 (connection reset)
and 14 code 1000 (EOF), all heartbeat requests. No response failures occurred
in either fixed mode. Each mode sent 520 measured heartbeats. This reproduces
the local timeout defect and supports the chosen settings, without proving
stage-0 performance. Per-endpoint counts, CPU, attempt outcomes and latencies
are retained in the raw reports, including unfinished attempts at the short
measurement boundary. The harness does not mimic the browser's 10 s stall behavior.

CI and Deploy check passed for tested HEAD `7d86961` (CI run 737, Deploy check 20).
The follow-up commit adds evidence only; its own CI status is reported in the PR.
Fresh-session independent review remains outstanding.
