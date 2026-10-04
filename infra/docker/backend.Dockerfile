# One Dockerfile, four images (Architecture section 10):
#   --target api           FastAPI API
#   --target worker        default worker pool: lanes ai, background
#   --target worker-media  media worker pool: lanes speech-interactive, intake
#   --target backup        nightly pg_dump to object storage (ADR 0032)
# Worker containers are healthy only once the pool has loaded its models and written
# its ready file (listenup.worker).
# Build from the repository root: docker build -f infra/docker/backend.Dockerfile --target api .

FROM python:3.12-slim AS base
RUN pip install --no-cache-dir "uv>=0.8,<0.9"
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/api/src ./src
COPY apps/api/alembic.ini ./
COPY apps/api/migrations ./migrations
RUN uv sync --frozen --no-dev && useradd --system --uid 10001 app

FROM base AS api
USER app
EXPOSE 8000
# Open event streams (GET /api/v1/events) would otherwise hold up a shutdown.
CMD ["uvicorn", "listenup.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "5"]

FROM base AS worker
USER app
HEALTHCHECK --interval=10s --start-period=30s CMD test -f /tmp/listenup-worker-ready
CMD ["python", "-m", "listenup.worker", "default"]

FROM base AS worker-media
# Media tools for download, conversion and snippet cutting. Speech models are
# added by the speech spikes (#18 to #21) and stay out of the other images.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && uv pip install --python /opt/venv/bin/python yt-dlp
USER app
HEALTHCHECK --interval=10s --start-period=120s CMD test -f /tmp/listenup-worker-ready
CMD ["python", "-m", "listenup.worker", "media"]

FROM base AS backup
# pg_dump and pg_restore 16, matching the server (PostgreSQL 16), from the PostgreSQL
# project's own repository: the Debian release in the base image may ship another major.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates postgresql-common \
    && /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && rm -rf /var/lib/apt/lists/* \
    && pg_dump --version | grep -q " 16\."
USER app
CMD ["python", "-m", "listenup.ops.backup", "schedule"]
