"""crawler — FastAPI application entry point.

Run: uvicorn app.main:app --port 8321 --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.browser import start as browser_start
from app.browser import stop as browser_stop
from app.config import settings, warn_insecure_config
from app.fetch import close_client
from app.routes import archive, auth, health, router, substack, x
from app.storage import ensure_bucket

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("crawler")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    warn_insecure_config()
    logger.info("starting crawler — engine=%s browser=%s archive=%s public=%s",
                settings.engine, settings.browser_enabled,
                bool(settings.s3_endpoint), settings.allow_public)
    ensure_bucket()
    await browser_start()
    yield
    # Shutdown
    await browser_stop()
    await close_client()
    logger.info("crawler stopped")


app = FastAPI(
    title="crawler",
    description="Best-effort content fetcher for X, Substack, and any URL.",
    version="0.1.0",
    lifespan=lifespan,
)

# Route registration
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(x.router)
app.include_router(substack.router)
app.include_router(router.router)
app.include_router(archive.router)
