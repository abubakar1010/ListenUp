"""API entry point: `uvicorn listenup.main:app`."""

from fastapi import APIRouter, FastAPI

from listenup import __version__

api = APIRouter(prefix="/api/v1")


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


def create_app() -> FastAPI:
    app = FastAPI(title="ListenUp API", version=__version__)
    app.include_router(api)
    return app


app = create_app()
