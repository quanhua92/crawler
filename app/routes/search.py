"""Search endpoint — GET /search?q=...&provider=auto|searxng|duckduckgo"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from app.auth import AuthedUser
from app.models import CrawlResponse
from app.ratelimit import rate_limit_or_auth
from app.sources.search import duckduckgo as ddg_src
from app.sources.search import searxng as searxng_src
from app.storage import persist

logger = logging.getLogger("crawler.routes.search")

router = APIRouter(tags=["search"])


@router.get("/search")
async def search(
    q: str = Query(..., description="search query"),
    _: AuthedUser | None = Depends(rate_limit_or_auth),
    provider: str = Query("auto", description="searxng | duckduckgo | auto"),
    limit: int = Query(10, ge=1, le=100),
    categories: str = Query("general", description="general, news, images, videos, it, science"),
    time_range: str | None = Query(None, description="day, week, month, year"),
    language: str | None = Query(None, description="language code (en, vi, ...)"),
    format: str = Query("json"),
):
    """Search the web via SearXNG (default) or DuckDuckGo (fallback)."""
    warnings: list[str] = []

    if provider in ("searxng", "auto"):
        try:
            posts, source, warnings = await searxng_src.search(
                q, limit=limit, categories=categories,
                time_range=time_range, language=language,
            )
            if posts:
                resp = CrawlResponse.ok(
                    items=posts, source=source,
                    engine="http", warnings=warnings,
                )
                await persist("search", "query", q,
                              {"provider": provider, "limit": limit,
                               "categories": categories}, resp)
                return resp
            warnings.append("searxng returned no results")
        except Exception as e:
            warnings.append(f"searxng failed: {type(e).__name__}: {e}")
            if provider == "searxng":
                resp = CrawlResponse.failed(
                    error=f"searxng error: {e}", warnings=warnings,
                )
                await persist("search", "query", q,
                              {"provider": provider, "limit": limit}, resp)
                return resp

    if provider in ("duckduckgo", "auto"):
        posts, source, ddg_warnings = await ddg_src.search(
            q, limit=limit, categories=categories,
            time_range=time_range, language=language,
        )
        warnings.extend(ddg_warnings)
        if posts:
            resp = CrawlResponse.ok(
                items=posts, source=source or "search:ddg",
                engine="http", warnings=warnings,
            )
        else:
            resp = CrawlResponse.failed(
                error="no results from any provider",
                warnings=warnings,
            )
        await persist("search", "query", q,
                      {"provider": provider, "limit": limit, "categories": categories}, resp)
        return resp

    resp = CrawlResponse.failed(
        error=f"unknown provider: {provider}",
        warnings=warnings,
    )
    await persist("search", "query", q, {"provider": provider}, resp)
    return resp
