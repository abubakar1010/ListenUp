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
