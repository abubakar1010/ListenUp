"""API entry point: `uvicorn listenup.main:app`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from listenup import __version__
from listenup.platform.config import Settings, get_settings
from listenup.platform.database import Database
from listenup.platform.errors import install_error_handlers
from listenup.platform.log import RequestIdMiddleware, configure_logging
from listenup.platform.rate_limit import RateLimiter
from listenup.platform.storage import S3Storage

api = APIRouter(prefix="/api/v1")


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.database = Database(settings.database_url, settings.database_pool_size)
        app.state.storage = S3Storage(settings)
        app.state.rate_limiter = RateLimiter(app.state.database)
        yield
        await app.state.database.dispose()

    app = FastAPI(title="ListenUp API", version=__version__, lifespan=lifespan)
    install_error_handlers(app)
    app.add_middleware(RequestIdMiddleware)  # added last, so it wraps everything
    app.include_router(api)
    return app


app = create_app()
