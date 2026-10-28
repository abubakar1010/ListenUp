# syntax=docker/dockerfile:1
# The edge image (#112): the production web build served by Caddy, which also
# terminates HTTPS and proxies /api to the API (infra/caddy/Caddyfile).
# Build from the repository root: docker build -f infra/docker/web.Dockerfile .
# Its build context is filtered by web.Dockerfile.dockerignore, not the root .dockerignore.

# The web build is plain static files, so it always runs on the builder's own
# architecture, even when the edge image is built for arm64 (ADR 0070).
FROM --platform=$BUILDPLATFORM node:22-alpine AS build
# Optional session CA for managed builders; ordinary CI uses system trust.
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    corepack enable && corepack prepare pnpm@10.28.0 --activate
WORKDIR /src/apps/web
COPY apps/web/package.json apps/web/pnpm-lock.yaml ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    pnpm install --frozen-lockfile
COPY apps/web ./
# The legal texts are imported from docs/legal at the repository root (ADR 0051).
COPY docs/legal /src/docs/legal
# Vite names every asset after its content hash (assets/<name>-<hash>.js).
RUN pnpm build

FROM caddy:2.10.2-alpine AS edge
COPY infra/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/apps/web/dist /srv
# Fail the build, not the deploy, on a Caddyfile that does not parse.
RUN LISTENUP_DOMAIN=example.org LISTENUP_ACME_EMAIL=ops@example.org \
    LISTENUP_MEDIA_ORIGIN=https://s3.example.org \
    caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
