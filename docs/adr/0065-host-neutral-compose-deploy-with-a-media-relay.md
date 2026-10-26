# ADR 0065: Host-neutral Compose deploys, an HTTPS edge image and a media relay

- Status: Accepted
- Date: 2026-10-25
- Story: #112 (live cutover pending the host choice in #16)
- Requirements: CI-A, NFR-SEC-1, NFR-REL-4; [Software Architecture 11 and 12.1](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13); [System Design 10 and 11.2](https://claude.ai/code/artifact/98274889-96ba-4424-afad-c2cd056206e2); [Database Design 9.1, 12.2 and 12.3](https://claude.ai/code/artifact/ba05f7b3-f881-41e5-86d6-dcb94a509644); ADRs 0031, 0032 and 0049

## Context

Production is one free VM running Docker Compose behind Caddy, with managed PostgreSQL, S3-compatible storage, an SMTP provider and a CDN for the web app (Architecture 11). A push to `main` that passes CI must be live within minutes, migrations first; all traffic must be HTTPS; the bucket must not be public; a rollback to the previous image must be documented and tested. The host (#16) is not chosen, so nothing may depend on one provider.

Three facts from the existing stack shape the design. The media worker's network is internal and isolated (ADR 0049); locally that works because PostgreSQL and storage are containers on that network, but managed services are outside the VM. The API keys rate limits and the sign-in lockout on the client address, which behind a reverse proxy is the proxy's unless forwarded addresses are trusted. And the web client calls `/api` on its own origin, with cookies and CSRF tokens that assume one origin.

## Decision

### One Compose file, one immutable tag

`infra/compose/compose.prod.yml` runs the edge, the API, both worker pools, the signature updater, model provisioning, the backup service and the relay. Every image is `${LISTENUP_REGISTRY}/listenup-<name>:${LISTENUP_IMAGE_TAG}`; the tag is `sha-<12 hex>` or `r<run number>`, both pushed for the same digest, never reused and never `latest`. Secrets come only from the host's `.env` (or a secret store that writes it), and each service receives only the variables it uses: reporting credentials only reach the API, the backup bucket's key only the backup service and the bucket check, SMTP and the hosted AI key only the default worker pool. Each process logs in as its own role (Database Design 9.1); `infra/deploy/bootstrap-roles.sql` creates them once on a managed server, including the BYPASSRLS attribute that only an administrator can grant.

### Deploy order and rollback

`infra/deploy/deploy.sh <tag>` pulls every image, runs the bucket check, runs `migrate` as a one-off container while the old release still serves, then `up --wait`. A failure before the restart leaves the running release untouched; a release that never becomes healthy is replaced by the previous containers. Rollback (`rollback.sh`) redeploys an earlier tag without migrating backwards. That is safe because migrations are expand-then-contract (Database Design 12.2): code from the previous release runs on the newer schema. A contract step (a drop) must ship at least one release after the code stops using what it drops, so the previous release stays deployable. An `alembic downgrade` is a manual exception after a fresh backup.

The deploy directory may hold a `compose.host.yml` with host-specific adjustments; it never comes from the repository.

### Release workflow, off by default

`.github/workflows/release.yml` runs after CI succeeds on a push to `main`, builds the six images from the commit CI tested and pushes them to GHCR with the workflow's own token. The deploy job connects over SSH with a pinned host key and runs only when the repository variable `LISTENUP_DEPLOY_ENABLED` is `true`, inside the `production` environment (which can require a reviewer). It ends with an HTTPS smoke test: health, the HTTP→HTTPS redirect and the security headers. `ci.yml` is unchanged; `deploy-check.yml` validates the compose file, scripts, workflows and edge image on every change before merge.

### HTTPS edge: Caddy with the web build, one origin

The edge image is Caddy with the Vite build in `/srv`. Caddy obtains and renews certificates itself and redirects HTTP to HTTPS; it sets HSTS, a CSP limited to the site and the storage origin, frame, referrer, opener and permission headers (microphone for this origin only), and removes `Server`. `/api/*` goes to the API; `/assets/*` (content-hashed) is cached for a year as immutable; every other path serves `index.html` with `no-cache`. The web app and the API therefore stay on one origin, so cookies and CSRF are unchanged, and any CDN can be put in front later without a code change. The web build and the edge ship as one versioned image, so a rollback restores both.

The API is published only through Caddy, which has a fixed address on the `edge` network. Uvicorn trusts `X-Forwarded-For` from that address alone (`--proxy-headers --forwarded-allow-ips`), and Caddy replaces any client-sent value. If a CDN is added, its address ranges become Caddy's `trusted_proxies`.

### The media relay

ADR 0049 limits the media worker to the database and storage on an internal network with no route out. Joining the egress network would give it the internet; host firewall rules would be host-specific and fragile against storage endpoints behind a CDN. Instead `db-relay` (HAProxy, TCP mode) sits on both networks with a fixed address on `media-data`, and forwards exactly two ports to the two configured upstreams; it reads nothing. The media worker's `extra_hosts` map the providers' real hostnames to the relay, so its URLs, and TLS certificate checks against the real names, are unchanged (database URLs use `sslmode=verify-full`, since `require` would accept any certificate); no other container sees that mapping, so the relay itself resolves the real addresses. It asks Docker's DNS again every 10 seconds, so a managed database's failover or a storage endpoint's new address reaches it without a restart. The fixed subnets and addresses have defaults that a host can move in its `.env` when its own networks use that range. The owner approved this exception to ADR 0049's "no proxies in the boundary": the relay is not a general proxy, adds no new destination, and the worker still cannot reach the API, mail, collectors or the internet.

### A public bucket stops a deploy

`python -m listenup.ops.storage_check` writes a probe object, makes an unsigned list and an unsigned read of it on every endpoint the bucket is served from (internal and browser-facing), and removes the probe. Any 2xx or 3xx answer means public (exit 1); an answer it cannot interpret means unknown (exit 2), and neither passes. Where the provider reports a bucket policy status, it must not say public. Unsigned requests are the test because providers express privacy in different ways (ACLs, policies, public-access blocks, dashboard settings).

## Consequences

- Moving to another host is the runbook's first-time setup on a new VM; no file in the repository changes.
- The managed database must allow an administrator to grant BYPASSRLS and CREATEROLE with admin option; #16 must check this before choosing a provider.
- Media and backup buckets need CORS for the site's origin (signed uploads and playback) and must stay private; the bucket check enforces only the second.
- `LISTENUP_ENVIRONMENT` defaults to `production`; a staging host sets `staging`, which keeps every non-local check (secure cookies, separate backup bucket, real consent versions, analytics key) but allows the fake AI configuration.
- Not verified until #16 provides a host: the real ACME certificate, DNS, the provider's database and bucket behaviour, the GHCR pull from the VM, SSH from Actions, real speech models and signature downloads at production size, and "live within minutes" end to end. `docs/runbooks/deploy.md` records the local rehearsal and lists these.
