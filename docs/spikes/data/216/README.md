# Local #216 evidence

These are reduced local synthetic runs, not stage-0 measurements. See
`docs/spikes/216-connection-timeouts.md` for provenance, limitations and stage-0 work.
Each run keeps the existing B5 harness's `results.json`, `results.md` and
`requests.csv.gz`; the private learner/token manifest is never included.

To reproduce, use the existing B5 harness and a fresh uniquely named Compose
project. Override host ports for PostgreSQL/storage/API and give k6 a unique
container name; never share a database/network with another session. Build the API
from the tested commit. In this workspace, local-only container `user: "0:0"`
was needed for source permissions; this is not a production recommendation.

Use the normal `infra/compose/compose.yml` and `spikes/load/compose.b5.yml` with
those local overrides. The control overrides the API command with
`--timeout-keep-alive 5`; fixed-direct uses its committed 30 s command. For
fixed-proxy, add `caddy:2.10.2-alpine`, mount the committed Caddyfile, set
`LISTENUP_DOMAIN=http://:8080`, a local ACME email and media origin, and give the
API the network alias `api-via-edge`. Use `--base-url http://edge:8080` for k6.

Common runner options:

```sh
spike-b5 --skip-up --project <unique-project> \
  --k6-network <unique-project>_default \
  --health-url http://localhost:<api-port>/api/v1/health \
  --database-url <isolated-owner-url> \
  --learners 25 --history 1 --blind-learners 20 --mixed-rps 15 \
  --warmup 20 --duration 120 --out <run-folder>
```

The unmodified harness hardcodes its k6 name. This run used a scratch Python
entrypoint assigning `listenup_spikes.b5_load.K6_CONTAINER` to
`listenup-216-verify-k6` before calling `main()`. It added Docker run environment
arguments `NO_PROXY=api,edge,localhost,127.0.0.1` and the same lowercase `no_proxy`
for k6 only. This prevents the environment's outbound proxy from handling these
local destinations. It leaves external network proxy settings intact and adds no
request retry or changes to the JS workload. Without it, the outbound proxy
returned 403 and no heartbeat load was delivered; those runs were discarded.

Run sequentially, let the runner delete its seeded learners/private manifest,
and keep results from each mode separately. Record the effective API command and
Caddy adaptation with the tested SHA. Restore the 5 s command for the control
before measuring; removing that override returns to 30 s for both fixed modes.

The scratch Caddy container also needs `NO_PROXY` and `no_proxy` containing
`api-via-edge,api,localhost,127.0.0.1` in this managed environment. Otherwise its
upstream traffic reaches the outbound proxy and is refused with `403 Loopback
targets forbidden`. That initial proxy run is excluded. Recreate the scratch
edge with the local exclusion before beginning the accepted proxy run.
