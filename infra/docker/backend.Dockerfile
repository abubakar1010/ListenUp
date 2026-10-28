# syntax=docker/dockerfile:1
# One Dockerfile, four images (Architecture section 10):
#   --target api           FastAPI API
#   --target worker        default worker pool: lanes ai, background
#   --target worker-media  media worker pool: lanes speech-interactive, intake
#   --target backup        nightly pg_dump to object storage (ADR 0032)
# Worker containers are healthy only once the pool has loaded its models and written
# its ready file (listenup.worker).
# Build from the repository root: docker build -f infra/docker/backend.Dockerfile --target api .

FROM python:3.12-slim AS base
# Optional session CA for managed builders; ordinary CI uses system trust.
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir "uv>=0.8,<0.9"
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export SSL_CERT_FILE=/run/secrets/proxy_ca; fi; \
    uv sync --frozen --no-dev --no-install-project
COPY apps/api/src ./src
COPY apps/api/alembic.ini ./
COPY apps/api/migrations ./migrations
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export SSL_CERT_FILE=/run/secrets/proxy_ca; fi; \
    uv sync --frozen --no-dev && useradd --system --uid 10001 app \
    && chmod -R a+rX /app/src /app/migrations /app/alembic.ini

FROM base AS api
USER app
EXPOSE 8000
# Open event streams (GET /api/v1/events) would otherwise hold up a shutdown.
CMD ["uvicorn", "listenup.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "5", "--timeout-keep-alive", "30"]

FROM base AS worker
USER app
HEALTHCHECK --interval=10s --start-period=30s CMD test -f /tmp/listenup-worker-ready
CMD ["python", "-m", "listenup.worker", "default"]

# Shared small runtime also used by the sandbox contract check. Signatures and
# speech weights are provisioned separately and mounted read-only by media jobs.
FROM base AS media-runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg clamav clamav-freshclam libseccomp2 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /scratch /models /signatures \
    && chown app /scratch /models /signatures
ENV PYTHONDONTWRITEBYTECODE=1 \
    TMPDIR=/scratch \
    HOME=/scratch \
    XDG_CACHE_HOME=/scratch/cache \
    LISTENUP_MEDIA_SCRATCH_DIR=/scratch \
    HF_HOME=/models/huggingface \
    TORCH_HOME=/models/torch
USER app

FROM media-runtime AS signature-update
COPY --chmod=0644 infra/docker/freshclam.conf /etc/clamav/listenup-freshclam.conf
CMD ["freshclam", "--config-file=/etc/clamav/listenup-freshclam.conf", "--daemon", "--foreground", "--stdout"]
HEALTHCHECK --interval=30s --start-period=300s CMD find /signatures -maxdepth 1 -name 'daily.c?d' -mtime -7 | grep -q .

# praat-parselmouth has no Linux arm64 wheel, so on arm64 this stage compiles it (on
# amd64 pip just downloads the published wheel). The compiler stays here: worker-media
# installs the wheel from this stage and never contains a toolchain (#232, ADR 0073).
# Keep the version equal to uv.lock; tests/unit/test_backend_dockerfile.py checks it.
FROM base AS parselmouth-wheel
ARG PARSELMOUTH_VERSION=0.4.7
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cmake \
    && rm -rf /var/lib/apt/lists/*
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca SSL_CERT_FILE=/run/secrets/proxy_ca; fi; \
    CMAKE_BUILD_PARALLEL_LEVEL="$(nproc)" \
    pip wheel --no-deps --wheel-dir /wheels "praat-parselmouth==${PARSELMOUTH_VERSION}"

FROM media-runtime AS worker-media
USER root
# Media tools for download, conversion and snippet cutting, and the self-hosted speech
# libraries (ADR 0028), which stay out of the other images. `uv sync` adds the locked
# `speech` extra first, because it removes packages the lock does not list; torch and
# torchaudio then come from the PyTorch CPU index (the PyPI wheels bundle CUDA).
# praat-parselmouth is skipped by `uv sync` and installed from the wheel stage above.
# The media-models service provisions /models; jobs mount it read-only.
ENV OMP_NUM_THREADS=2 \
    HF_HOME=/models/huggingface \
    TORCH_HOME=/models/torch
RUN --mount=type=secret,id=proxy_ca \
    --mount=type=bind,from=parselmouth-wheel,source=/wheels,target=/wheels \
    if [ -f /run/secrets/proxy_ca ]; then export SSL_CERT_FILE=/run/secrets/proxy_ca; fi; \
    uv sync --frozen --no-dev --extra speech --no-install-package praat-parselmouth \
    && uv pip install --python /opt/venv/bin/python --no-deps /wheels/*.whl \
    && uv pip install --python /opt/venv/bin/python \
        --index-url https://download.pytorch.org/whl/cpu "torch>=2.4,<2.9" "torchaudio>=2.4,<2.9" \
    && uv pip install --python /opt/venv/bin/python yt-dlp \
    && mkdir -p /models && chown app /models
USER app
# Provisioned models are loaded before the pool reports ready.
HEALTHCHECK --interval=10s --start-period=600s CMD test -f /scratch/listenup-worker-ready
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
