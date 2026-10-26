# Deploy and rollback runbook

Production is one Docker-capable VM running `compose.prod.yml` behind Caddy, with managed PostgreSQL 16, S3-compatible storage and an SMTP provider (Architecture 11). Design and reasons: [ADR 0066](../adr/0066-host-neutral-compose-deploy-with-a-media-relay.md). Nothing here names a provider: the host is chosen in #16. Times are UTC.

| What | Where |
| --- | --- |
| Stack | `infra/compose/compose.prod.yml`, copied to `/opt/listenup/compose.prod.yml` by each deploy |
| Deploy and rollback | `infra/deploy/deploy.sh`, `infra/deploy/rollback.sh`, copied to `/opt/listenup/bin/` |
| Every variable the stack reads | `infra/deploy/env.example` (placeholders only) |
| Host secrets | `/opt/listenup/.env`, mode 0600, owned by the deploy user; never in the repository |
| Release state | `/opt/listenup/state/current-tag`, `previous-tag`, `releases.log` |
| Workflow | `.github/workflows/release.yml` (Actions → Release) |
| Images | `ghcr.io/abubakar1010/listenup-{edge,api,worker,worker-media,backup,signature-update}` at `sha-<12 hex>` and `r<run number>` |

## How a release reaches production

1. A push to `main` runs CI. When CI succeeds, the **Release** workflow builds the six images from that exact commit and pushes them with two tags: `sha-<first 12 of the commit>` and `r<run number>`. Nothing is tagged `latest`, and a tag is never reused: a commit is built once, and a re-run or a later manual deploy of the same commit only adds a new `r<n>` tag to the existing images.
2. If `LISTENUP_DEPLOY_ENABLED` is `true`, the deploy job (environment `production`) copies `compose.prod.yml` and the scripts to the host over SSH and runs `deploy.sh sha-<…>`:
   1. pull every image (a missing image fails before anything changes);
   2. `storage-check`: a public or unreadable media or backup bucket stops the deploy;
   3. `migrate`: `alembic upgrade head` as a one-off container, as `listenup_owner`, while the old release still serves. A failure stops here; the running release is untouched;
   4. `up --detach --wait --remove-orphans`: containers are replaced and must pass their health checks. If the new release never becomes healthy, the previous release's containers are started again and the job fails;
   5. record the tags in `state/` and `releases.log`.
3. The job then checks `https://<domain>/api/v1/health`, that `http://` answers 308 to `https://`, and that the security headers are present.

Expected time from merge to live: CI (about 10 minutes) plus image builds (a few minutes with the build cache) plus the deploy (15 to 40 seconds in the rehearsal below, pulls included, from a registry on the same machine). The real figure on the host is unverified until #16.

Replacing the containers interrupts service for a few seconds (about 7 s in the rehearsal: the API restarts, then Caddy). The web app keeps drafts and marks locally and resends them (NFR-REL-1), and the event stream reconnects. A failed release that is replaced by the running one costs about 14 s.

Migrations are expand-only (Database Design 12.2), so the release that was running keeps working on the migrated schema. A contract step (dropping a column or table) ships at least one release after the code stopped using it, so the previous release always stays deployable.

## Deploy by hand

From Actions → Release → Run workflow, on `main`: `action=deploy` with an empty tag builds and deploys `main`; with a tag (`r41`), it redeploys those images (migrations run) with the compose file and scripts of the commit they were built from, read from the images' `org.opencontainers.image.revision` label. Or on the host, as the deploy user:

```sh
LISTENUP_DEPLOY_DIR=/opt/listenup /opt/listenup/bin/deploy.sh r41
```

## Roll back to the previous image tag

Use this when a release misbehaves after it went live (errors, a broken page, a failing job type). Rolling back changes only the images; it never migrates backwards.

1. Actions → Release → Run workflow → `action=rollback`, tag empty (the host's previous release). Or on the host:

   ```sh
   LISTENUP_DEPLOY_DIR=/opt/listenup /opt/listenup/bin/rollback.sh                # previous release
   LISTENUP_DEPLOY_DIR=/opt/listenup /opt/listenup/bin/rollback.sh --force r39    # an older one
   ```

   Only the previous release is sure to run on the current schema: a contract step (a drop) may ship one release after its code stopped using what it drops (Database Design 12.2). A named tag other than the previous release is refused unless forced (`force` in the workflow). Force it only after reading the migrations of every release since that tag and finding no drop of anything it reads.

2. Check: `curl -fsS https://<domain>/api/v1/health`, `docker compose -p listenup ps` (all healthy), `cat /opt/listenup/state/current-tag`.
3. Afterwards `previous-tag` names the release rolled away from, so a second `rollback.sh` returns to it once it is fixed. Fix forward with a new commit; do not redeploy the bad tag.
4. Only if a migration itself is the problem: take a backup (`docker compose -p listenup --env-file .env -f compose.prod.yml exec backup python -m listenup.ops.backup dump`), then run `alembic downgrade -1` from the `migrate` service of the **newer** release (`LISTENUP_IMAGE_TAG=<newer tag> docker compose ... run --rm migrate alembic downgrade -1`), then roll back. This is the exception: record it in the incident notes.

The compose file in `/opt/listenup` stays the newer release's; compose changes follow the same expand-then-contract rule, so the previous release's images run with it. If a release changed the compose file incompatibly, copy that older release's `infra/compose/compose.prod.yml` to the host before rolling back.

## First-time host setup

Host selection and Docker-only provisioning are tracked in #16. Check
[ADR 0067](../adr/0067-stage-zero-host-eligibility-and-provisioning-gate.md) and the
[stage-0 host checklist](stage-zero-host.md) before the steps below. No reachable
host is verified yet. The current media container has an 18 GiB memory ceiling
and no swap allowance (`memswap_limit` equals `mem_limit`); the 16 GB figure below
is not sufficient for the full configured ceiling plus other services. The
recommended planning budget is 24 GiB RAM and 80 GiB disk, pending measurement.
Host provisioning alone must not enable production deployment; steps that add
production credentials, run the application or enable Release belong to #112.

Do these once per host, in order. Each step says what it proves.

1. **VM.** Any Linux VM with at least 4 cores and 16 GB of memory for the speech models (Architecture 11; the media worker is capped at 2 cores and 18 GB including swap), 40 GB of disk, a public IPv4 address, and outbound HTTPS. Install Docker Engine 28 or later and the Compose plugin 2.24 or later (ADR 0049's isolated bridge needs both): `docker version`, `docker compose version`.
2. **Firewall.** Inbound: 22 (SSH, restricted to the owner's addresses where the provider allows it), 80 and 443 TCP, and 443 UDP (HTTP/3). Nothing else; only the `edge` container publishes ports.
3. **Deploy user.** Create `deploy`, add it to the `docker` group, put the release workflow's public key in `~deploy/.ssh/authorized_keys`, disable password login. Record the host key for GitHub: `ssh-keyscan -t ed25519 <host>`, or `ssh-keyscan -p <port> -t ed25519 <host>` when SSH listens on another port (the line then starts `[<host>]:<port>`, which is what the deploy job looks up). Compare its fingerprint with the provider's console.
4. **DNS.** An `A` (and `AAAA` if IPv6) record from the domain to the VM. Caddy needs it before the first deploy to get the certificate.
5. **Managed PostgreSQL 16.** In a region close to the VM. The provider's administrator must be able to grant BYPASSRLS and CREATEROLE (check before choosing the provider); it need not be a superuser. Generate four random passwords of printable ASCII (for example `openssl rand -base64 32`). The script takes SCRAM verifiers, never the passwords, so nothing in the server's logs can reveal them. From a checkout of this repository on any machine that reaches the database:

   ```sh
   cd apps/api
   verifier() { printf '%s' "$1" | uv run python -m listenup.ops.scram_verifier; }
   psql "$ADMIN_URL" -v ON_ERROR_STOP=1 \
     -v owner_verifier="$(verifier "$OWNER_PW")" -v api_verifier="$(verifier "$API_PW")" \
     -v worker_verifier="$(verifier "$WORKER_PW")" -v readonly_verifier="$(verifier "$READONLY_PW")" \
     -f ../../infra/deploy/bootstrap-roles.sql
   ```

   It refuses anything that is not a verifier, and stops if `PUBLIC` could still connect to the database. It prints the four roles: all `login`, only `listenup_worker` with `bypassrls`, none `superuser`. Turn on the provider's daily backups (or point-in-time recovery) and record the retention in `backups.md`; enable `pg_stat_statements` and the provider's alerts for connections near the limit and storage (Database Design 12.3). Every database URL uses `sslmode=verify-full` with `sslrootcert` (as in `env.example`): `require` would encrypt but accept any certificate, and the media pool reaches the database through the relay. If the provider's certificate chains to its own CA rather than a public one, mount that CA file into the database-using services in `compose.host.yml` and point `sslrootcert` at it.
6. **Storage.** Two private buckets: media and backups, each with its own key that has rights on that bucket only (ADR 0032). Turn on server-side encryption if it is not the default. Give the media bucket a CORS rule for `https://<domain>`, methods `GET`, `PUT` and `HEAD`, header `*`, so signed uploads and playback work from the browser. Turn off every way the provider can serve the buckets publicly (a public-access setting, a provider "dev" or public domain, a custom domain bound to the bucket, a CDN in front), and record in the release notes of the first deploy which settings were checked: `storage-check` only probes the S3 endpoints in `.env`, and on a provider without `GetBucketPolicyStatus` it reports the policy as `unsupported` rather than failing. Make each key able to write and delete `ops/public-access-probe.txt` in its bucket, which `storage-check` writes before every deploy.
7. **SMTP.** An account with the provider, the sender domain verified (SPF and DKIM records).
8. **Registry access.** A GitHub token with only `read:packages`, then on the host as `deploy`: `echo "$TOKEN" | docker login ghcr.io -u <github user> --password-stdin`.
9. **Environment file.** `sudo install -d -o deploy -m 0750 /opt/listenup`, then create `/opt/listenup/.env` from `infra/deploy/env.example` with mode 0600. `LISTENUP_RELAY_DB_HOST` and `LISTENUP_RELAY_S3_HOST` must be the exact hostnames in the database URLs and the S3 endpoint (never IP addresses), with their ports. `LISTENUP_MEDIA_ORIGIN` is the scheme and host of `LISTENUP_S3_PUBLIC_ENDPOINT_URL`. Compose substitutes `$` inside unquoted values, so single-quote any value that contains `$` (`LISTENUP_SMTP_PASSWORD='pa$$word'`); passwords made with `openssl rand -base64` contain none. If the host's own networks use 172.31.250.0/24 or 172.31.251.0/24, set the four optional network variables at the end of the relay section.
10. **Check before the first deploy.** Copy `compose.prod.yml` to `/opt/listenup`, then `LISTENUP_IMAGE_TAG=r1 docker compose -p listenup --env-file .env -f compose.prod.yml --profile ops config --quiet` (every variable is set).
11. **GitHub.** Create the environment `production` (Settings → Environments), optionally with a required reviewer. Add its secrets `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` (the private key from step 3) and `DEPLOY_SSH_KNOWN_HOSTS` (the `ssh-keyscan` line), and the repository variables `LISTENUP_PUBLIC_URL` (`https://<domain>`), optionally `LISTENUP_DEPLOY_DIR` and `LISTENUP_DEPLOY_SSH_PORT`. Last, set `LISTENUP_DEPLOY_ENABLED` to `true`: from then on every green `main` deploys.
12. **First deploy.** Actions → Release → Run workflow (`deploy`, empty tag). Then check the certificate (`curl -vI https://<domain>` shows a Let's Encrypt or ZeroSSL issuer) and the redirect (`curl -I http://<domain>` → 308).
13. **Monitoring.** Set up the external uptime monitor on `https://<domain>/api/v1/health` every 5 minutes, outside the VM, and the production Alertmanager receiver (`alerts.md`, "Where alerts go"). Run the first production restore test (`backups.md`).

## Secrets and their rotation

Values never enter the repository, a commit message, an issue or a log. After changing a value in `/opt/listenup/.env`, apply it with `docker compose -p listenup --env-file .env -f compose.prod.yml up -d --wait` (only the containers whose variables changed are recreated) and check health.

| Secret (name in `.env` or GitHub) | Used by | Rotate |
| --- | --- | --- |
| `LISTENUP_MIGRATE_DATABASE_URL`, `LISTENUP_API_DATABASE_URL`, `LISTENUP_WORKER_DATABASE_URL`, `LISTENUP_TRANSCRIPT_READ_DATABASE_URL`, `LISTENUP_ADMIN_REPORT_DATABASE_URL` (passwords of `listenup_owner`, `_api`, `_worker`, `_readonly`) | migrate and backup; API; both worker pools and the API's transcript gate; admin reports | Re-run `bootstrap-roles.sql` with the new password's verifier for that role and `keep` for the other three (for example `-v api_verifier="$(verifier "$NEW_API_PW")" -v owner_verifier=keep -v worker_verifier=keep -v readonly_verifier=keep`), update the URL(s) in `.env`, `up -d --wait`. Existing connections keep working until the containers restart. |
| `LISTENUP_S3_ACCESS_KEY`, `LISTENUP_S3_SECRET_KEY` | API, both worker pools, storage check | Create a second key for the media bucket, put it in `.env`, `up -d --wait`, check an upload and playback, then delete the old key. |
| `LISTENUP_BACKUP_S3_ACCESS_KEY`, `LISTENUP_BACKUP_S3_SECRET_KEY` | backup, storage check | As above for the backup bucket; then `exec backup python -m listenup.ops.backup list`. |
| `LISTENUP_SMTP_USERNAME`, `LISTENUP_SMTP_PASSWORD` | default worker pool | New credential at the provider, `.env`, `up -d --wait`, request a password reset to a test address, revoke the old one. |
| `LISTENUP_GOOGLE_CLIENT_SECRET` | API | Add a new secret in the Google console, `.env`, `up -d --wait`, sign in with Google, delete the old secret. |
| `LISTENUP_ANALYTICS_HMAC_KEY` | API, workers, backup, migrate | Rotating it breaks the link between old and new pseudonymous analytics ids (ADR 0035): rotate only after a suspected leak, and note the date for analysis. |
| `LISTENUP_AI_GROQ_API_KEY`, `LISTENUP_OTEL_HEADERS` | default worker pool; API, worker, backup | New key at the provider, `.env`, `up -d --wait`, revoke the old key. |
| Registry token (`docker login` on the host) | the host's image pulls | New `read:packages` token, `docker login ghcr.io` again, `deploy.sh <current tag>` to prove a pull, revoke the old token. |
| `DEPLOY_SSH_KEY` (GitHub environment secret) | the deploy job | New key pair, add its public key to `authorized_keys`, update the secret, run a manual redeploy of the current tag, remove the old public key. |
| `DEPLOY_SSH_KNOWN_HOSTS` | the deploy job | Only when the host key changes (a rebuilt VM): `ssh-keyscan` again and verify the fingerprint out of band. |

If a secret leaked, rotate it first, then check the provider's access logs for its use.

## Rebuilding the server elsewhere

The managed database and the buckets survive the VM. On the new VM, follow first-time setup steps 1 to 4 and 8 to 11 (the database, storage and SMTP already exist), copy the `.env` from the secret store, then run a manual deploy of the tag in `releases.log` (or the newest). Update DNS. See `backups.md` if the database was lost too.

## Rehearsal record

The whole flow was rehearsed on 2026-10-25, before any host existed. A single Docker 29.9 machine (cgroup v1) ran stand-ins for the managed services in a separate Compose project on the network `listenup-managed`:

- PostgreSQL 16 with an `admin` superuser (`db.managed.test`);
- SeaweedFS with separate media and backup keys, each limited to its own bucket (`s3.managed.test`);
- Mailpit as the SMTP provider (`smtp.managed.test`);
- a local `registry:2.8.3` in place of GHCR.

The deploy directory held the release's `compose.prod.yml`, a `.env` with the rehearsal values (`LISTENUP_ENVIRONMENT=staging` and `ai.fake.yaml`, since the real speech models are a multi-gigabyte download), and a `compose.host.yml` that made `listenup-managed` the stack's egress network.

The domain was `listenup.localhost`: Caddy issued its certificate from its internal CA, which the checks trusted explicitly. The images were built with this repository's Dockerfiles. The sandbox's TLS-intercepting proxy needed one rehearsal-only change: the scratch copy of `backend.Dockerfile` let apt trust the proxy's CA (the CA file was also mounted into `media-signatures`). Neither change is in the repository.

| Step | Result |
| --- | --- |
| `bootstrap-roles.sql`, run twice | Four login roles; only `listenup_worker` has BYPASSRLS; none is a superuser. The second run changed nothing and rotated the passwords. |
| `bootstrap-roles.sql` as a non-superuser administrator (review fix, 2026-10-26; scratch PostgreSQL 16.15, admin with `CREATEROLE CREATEDB BYPASSRLS` only) | The first version stopped at `CREATE DATABASE` ("must be able to SET ROLE listenup_owner"), its `REVOKE CONNECT` only warned (`PUBLIC` kept `CONNECT` and `TEMPORARY`), and a failing `ALTER ROLE` put the plain password in the server log. The fixed script ran clean; `datacl` lists only the four roles; a role outside them was refused (`User does not have CONNECT privilege`); a plain password was refused before any statement carried it; rotating `listenup_api` with `keep` for the others left their passwords working; the server log held no password. |
| `deploy.sh r1` (first try) | Stopped after the bucket check and migrations: Compose cannot put an inline config in a read-only container. No release was recorded. The relay no longer sets `read_only` (fixed in this story). |
| `deploy.sh r1` | Live in 15 s. All images were pulled from the registry. Both buckets were private. `alembic upgrade head` ran as `listenup_owner` (not a superuser) with no extra grants. Every service was healthy. |
| HTTPS checks | Health returned 200 over HTTP/2 with the certificate verified. `http://` answered 308 to `https://`. HSTS, CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` and COOP were present, with no `Server` header. `/assets/*` came back immutable for a year (zstd). App routes served `index.html` with `no-cache`, and a missing asset was a 404. Only `edge` published ports: 80, 443 and 443/udp. |
| Browser | Chromium (Playwright) loaded sign-in, registration, the library, settings, add clip and a content page: no CSP violations. |
| Client addresses | Found a bug: the API saw Caddy's egress-network address, so every learner would have shared one address for rate limits and the lockout. After the fix (`api-via-edge`), the API saw each real client address, and a spoofed `X-Forwarded-For` was discarded. |
| Media boundary | From the media worker: the database and storage were reachable through the relay at 172.31.251.10. The API, SMTP, the internet, `pypi.org` and the edge network were not. The media pool's database sessions arrived from the relay's address. |
| Learner flow (each release) | Register, then sign in (`__Host-` `Secure` cookies). The default worker delivered the reset email over SMTP. A signed PUT reached the private bucket, and the same object without a signature returned 403. The upload was confirmed, and the sandboxed media worker scanned it with real ClamAV signatures and converted it to `playable` (45 s). |
| Backup | The dump went to the backup bucket with the backup key. The restore test passed (38 tables, 58 rows, 0.53 s). The API's key was refused on the backup bucket. |
| `deploy.sh r2` | r2 is this branch plus a rehearsal-only expand migration (a new table and a new column). Live in 40 s: the migration ran before the restart, and the state read `current r2`, `previous r1`. |
| `rollback.sh` | Back to r1 in 19 s, with no migration and no bucket check. Health was probed every 0.25 s: 27 of 334 requests failed, over about 7 s. On r2's schema, r1 signed in the learner created on r2, and a new learner completed the whole flow. |
| `deploy.sh r3` (migrations fail) | The r1 images, retagged, cannot apply to the newer schema (`Can't locate revision`). The deploy stopped at `migrate` with "running release r1 is untouched". The probe stayed 167/167 healthy, and no release was recorded. |
| `deploy.sh r4` (API never healthy) | A first try stopped at the bucket check, because the broken API image also runs it. With the image failing only on uvicorn: "container listenup-api-1 is unhealthy". r2 was started again, the deploy exited 1, and the state stayed r2 (about 14 s unavailable). |
| Review fixes (2026-10-26, no Docker daemon) | `bootstrap-roles.sql` on a scratch PostgreSQL 16.15 under a non-superuser admin: see the row above. A verifier from `listenup.ops.scram_verifier` signed in over SCRAM, and a wrong password was refused. `haproxy -c` (2.8) accepted the relay config with the DNS resolvers and kept starting when the provider names did not resolve; the earlier config failed to start ("could not resolve address"). The Caddyfile ran on Caddy 2.6.2 (plain HTTP, the API stubbed): a missing asset was a 404 without `Cache-Control`, an existing one stayed immutable for a year, app routes stayed `no-cache`, and the event stream reached the client uncompressed and at once. `caddy validate` passed. The image build still validates with the pinned Caddy 2.10.2. |

## Not verified until a host exists (#16)

These are checked at the live cutover, which keeps #112 open:

- A real ACME certificate, its renewal, DNS, and HTTP/3 through the provider's firewall.
- The managed PostgreSQL provider:
  - granting BYPASSRLS and CREATEROLE, and `bootstrap-roles.sql` under its administrator (rehearsed only on a scratch PostgreSQL 16 with a non-superuser admin);
  - `sslmode=verify-full` with the image's CA bundle against its certificate (or its own CA mounted);
  - TLS connections through the relay;
  - its connection limit with the API, both pools and the backup service;
  - its own backups and alerts.
- The storage provider:
  - its answer to unsigned requests and to `GetBucketPolicyStatus`, and every other route by which it can serve a bucket publicly;
  - CORS from the site's origin;
  - key scoping per bucket;
  - signed URLs from a real browser on the internet (the rehearsal browser could not resolve the stand-in storage name).
- The SMTP provider with STARTTLS and authentication; SPF and DKIM.
- GHCR pushes from Actions, reuse of an existing build and the commit lookup of a named redeploy (`skopeo inspect`), the host's read-only pull, SSH with a pinned host key, the `production` environment gate, and the workflow's smoke test.
- Time from merge to live on GitHub's runners and the VM.
- Real speech models in `media-models`, and the media worker's memory and CPU on the host (#155 holds the performance checks).
- Docker 28+ on cgroup v2 hosts (the rehearsal machine used cgroup v1).
- The external uptime monitor, the production Alertmanager receiver, and the first production restore test.
