# One Dockerfile, three images (Architecture section 10):
#   --target api           FastAPI API
#   --target worker        default worker pool: lanes ai, background
#   --target worker-media  media worker pool: lanes speech-interactive, intake
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
CMD ["uvicorn", "listenup.main:app", "--host", "0.0.0.0", "--port", "8000"]

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
