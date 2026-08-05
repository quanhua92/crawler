"""X (Twitter) routes — feeds, single posts, threads."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from app.auth import AuthedUser
from app.models import CrawlResponse
from app.ratelimit import rate_limit_or_auth
from app.sources.x import nitter as nitter_src
from app.sources.x import syndication as syndication_src
from app.storage import persist

logger = logging.getLogger("crawler.routes.x")

router = APIRouter(prefix="/x", tags=["x"])


@router.get("/{handle}")
async def x_feed(
    handle: str,
    _: AuthedUser | None = Depends(rate_limit_or_auth),
    limit: int = Query(20, ge=1, le=100),
    engine: str = Query("auto"),
    format: str = Query("json"),
):
    """X user feed via Nitter RSS (multi-instance rotation)."""
    handle = handle.lstrip("@")
    warnings: list[str] = []

    try:
        posts, source, warnings = await nitter_src.fetch_feed(handle, limit=limit)
    except Exception as e:
        logger.exception("x feed failed for %s", handle)
        resp = CrawlResponse.failed(error=f"{type(e).__name__}: {e}", warnings=warnings)
        await persist("x", "feed", handle, {"limit": limit, "engine": engine}, resp)
        return resp

    if posts:
        resp = CrawlResponse.ok(items=posts, source=source, engine="http", warnings=warnings)
    else:
        resp = CrawlResponse.failed(
            error="all nitter instances exhausted or empty",
            warnings=warnings or ["no instances returned data"],
        )

    await persist("x", "feed", handle, {"limit": limit, "engine": engine}, resp)
    return resp


@router.get("/status/{tweet_id}")
async def x_post(
    tweet_id: str,
    _: AuthedUser | None = Depends(rate_limit_or_auth),
    engine: str = Query("auto"),
    format: str = Query("json"),
):
    """Single X post via syndication JSON (no Nitter dependency)."""
    try:
        post = await syndication_src.fetch_tweet(tweet_id)
    except Exception as e:
        logger.exception("x post failed for %s", tweet_id)
        resp = CrawlResponse.failed(error=f"{type(e).__name__}: {e}")
        await persist("x", "post", tweet_id, {"engine": engine}, resp)
        return resp

    if post:
        resp = CrawlResponse.ok(item=post, source="syndication", engine="http")
    else:
        resp = CrawlResponse.failed(error=f"tweet {tweet_id} not found or rate-limited")

    await persist("x", "post", tweet_id, {"engine": engine}, resp)
    return resp


@router.get("/status/{tweet_id}/thread")
async def x_thread(
    tweet_id: str,
    _: AuthedUser | None = Depends(rate_limit_or_auth),
    engine: str = Query("auto"),
    format: str = Query("json"),
):
    """Walk a reply chain upward via syndication JSON."""
    try:
        chain = await syndication_src.fetch_thread(tweet_id)
    except Exception as e:
        logger.exception("x thread failed for %s", tweet_id)
        resp = CrawlResponse.failed(error=f"{type(e).__name__}: {e}")
        await persist("x", "thread", tweet_id, {"engine": engine}, resp)
        return resp

    if chain:
        resp = CrawlResponse.ok(items=chain, source="syndication", engine="http")
    else:
        resp = CrawlResponse.failed(error=f"thread from {tweet_id} not found")

    await persist("x", "thread", tweet_id, {"engine": engine}, resp)
    return resp
