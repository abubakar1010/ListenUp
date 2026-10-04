"""API entry point: `uvicorn listenup.main:app`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from listenup import __version__
from listenup.modules.blind import api as blind_api
from listenup.modules.content import api as content_api
from listenup.modules.content.service import build_uploads
from listenup.modules.dictation import api as dictation_api
from listenup.modules.identity import api as identity_api
from listenup.modules.identity.service import build_accounts, current_learner
from listenup.modules.library import api as library_api
from listenup.modules.practice import api as practice_api
from listenup.platform.config import Settings, get_settings
from listenup.platform.csrf import CsrfMiddleware
from listenup.platform.database import Database
from listenup.platform.errors import install_error_handlers
from listenup.platform.events import EventHub, EventListener, events_router
from listenup.platform.log import RequestIdMiddleware, configure_logging
from listenup.platform.rate_limit import RateLimiter
from listenup.platform.storage import S3Storage
from listenup.platform.telemetry import (
    TelemetryMiddleware,
    configure_telemetry,
    shutdown_telemetry,
)


def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_telemetry(settings, "api")
        app.state.database = Database(settings.database_url, settings.database_pool_size)
        app.state.storage = S3Storage(settings)
        app.state.rate_limiter = RateLimiter(app.state.database)
        app.state.accounts = build_accounts(app.state.database, app.state.rate_limiter, settings)
        app.state.uploads = build_uploads(settings, app.state.storage, app.state.rate_limiter)
        app.state.events = EventHub()
        app.state.event_listener = EventListener(settings.database_url, app.state.events)
        app.state.event_listener.start()
        yield
        app.state.events.close()
        await app.state.event_listener.stop()
        await app.state.database.dispose()
        shutdown_telemetry()

    app = FastAPI(title="ListenUp API", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    install_error_handlers(app)
    app.add_middleware(CsrfMiddleware, secure=settings.cookies_secure)
    app.add_middleware(TelemetryMiddleware)  # inside RequestIdMiddleware, to see the id
    app.add_middleware(RequestIdMiddleware)  # added last, so it wraps everything
    api = APIRouter(prefix="/api/v1")
    api.add_api_route("/health", health, methods=["GET"])
    api.include_router(identity_api.router)
    api.include_router(content_api.router)
    api.include_router(library_api.router)
    api.include_router(practice_api.router)
    api.include_router(blind_api.router)
    api.include_router(dictation_api.router)
    api.include_router(events_router(current_learner))
    app.include_router(api)
    return app


app = create_app()
