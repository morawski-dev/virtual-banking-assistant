import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from mock_cb.rag.indexer import build_index
from mock_cb.routes import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.rag_index = build_index()  # None on failure / missing key → stub fallback
        yield

    app = FastAPI(
        title="Mock Core Banking",
        version="0.1.0",
        description="Mock Core Banking REST API for demo purposes — hardcoded Jan Kowalski fixture.",
        lifespan=lifespan,
    )
    app.include_router(router)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app


app = create_app()
