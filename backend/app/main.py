"""FastAPI application entrypoint.

Run with:  uvicorn app.main:app --reload
Workers either run in-process (RUN_WORKERS_IN_APP=true) or in the dedicated
worker container (`python -m app.workers.runner`).
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routers import analytics, graph, markets, opportunities, portfolio, system
from app.api.ws import manager
from app.api.ws import router as ws_router
from app.config import get_settings
from app.db.base import dispose_engine, init_db
from app.logging_config import get_logger, setup_logging

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    await init_db()
    await manager.start()

    orchestrator = None
    orchestrator_task = None
    if settings.run_workers_in_app:
        from app.workers.orchestrator import Orchestrator

        orchestrator = Orchestrator()
        orchestrator_task = asyncio.create_task(orchestrator.run())
        log.info("workers running in-app")

    log.info("API ready (v%s)", __version__)
    yield

    if orchestrator is not None:
        orchestrator.stop()
        if orchestrator_task is not None:
            try:
                await asyncio.wait_for(orchestrator_task, timeout=10)
            except (asyncio.TimeoutError, Exception):
                pass
    await manager.stop()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Polymarket Edge",
        description="Automated prediction-market trading platform: scanning, edge detection, "
        "AI analysis, risk management, execution, and backtesting.",
        version=__version__,
        lifespan=lifespan,
    )
    origins = [o.strip() for o in settings.cors_origins.split(",")] if settings.cors_origins else ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(system.router)
    app.include_router(markets.router)
    app.include_router(opportunities.router)
    app.include_router(portfolio.router)
    app.include_router(analytics.router)
    app.include_router(graph.router)
    app.include_router(ws_router)
    return app


app = create_app()
