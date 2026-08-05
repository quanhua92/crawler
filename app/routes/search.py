"""Search endpoint — GET /search?q=... or POST /search with JSON body.

GET is standard (bookmarkable, cacheable). POST avoids encoding issues
with special chars (c++, quotes, &, long queries).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.auth import AuthedUser
from app.models import CrawlResponse
from app.ratelimit import rate_limit_or_auth
from app.sources.search import duckduckgo as ddg_src
from app.sources.search import searxng as searxng_src
from app.storage import persist

logger = logging.getLogger("crawler.routes.search")

router = APIRouter(tags=["search"])


class SearchBody(BaseModel):
    """POST /search request body — same params as GET, no encoding issues."""

    q: str
    provider: str = "auto"
    limit: int = 10
    categories: str = "general"
    time_range: str | None = None
    language: str | None = None


async def _do_search(
    query: str,
    provider: str,
    limit: int,
    categories: str,
    time_range: str | None,
    language: str | None,
) -> CrawlResponse:
    """Shared search logic for GET + POST."""
    warnings: list[str] = []

    if provider in ("searxng", "auto"):
        try:
            posts, source, warnings = await searxng_src.search(
                query, limit=limit, categories=categories,
                time_range=time_range, language=language,
            )
            if posts:
                resp = CrawlResponse.ok(
                    items=posts, source=source,
                    engine="http", warnings=warnings,
                )
                await persist(
                    "search", "query", query,
                    {"provider": provider, "limit": limit,
                     "categories": categories}, resp,
                )
                return resp
            warnings.append("searxng returned no results")
        except Exception as e:
            warnings.append(f"searxng failed: {type(e).__name__}: {e}")
            if provider == "searxng":
                resp = CrawlResponse.failed(
                    error=f"searxng error: {e}", warnings=warnings,
                )
                await persist(
                    "search", "query", query,
                    {"provider": provider, "limit": limit}, resp,
                )
                return resp

    if provider in ("duckduckgo", "auto"):
        posts, source, ddg_warnings = await ddg_src.search(
            query, limit=limit, categories=categories,
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
        await persist(
            "search", "query", query,
            {"provider": provider, "limit": limit,
             "categories": categories}, resp,
        )
        return resp

    resp = CrawlResponse.failed(
        error=f"unknown provider: {provider}",
        warnings=warnings,
    )
    await persist("search", "query", query, {"provider": provider}, resp)
    return resp


@router.get("/search")
async def search_get(
    q: str = Query(..., description="search query"),
    _: AuthedUser | None = Depends(rate_limit_or_auth),
    provider: str = Query("auto"),
    limit: int = Query(10, ge=1, le=100),
    categories: str = Query("general"),
    time_range: str | None = Query(None),
    language: str | None = Query(None),
):
    """Web search via GET (standard, bookmarkable).

    For queries with special chars (c++, &, quotes), use POST instead.
    """
    return await _do_search(q, provider, limit, categories, time_range, language)


@router.post("/search")
async def search_post(
    body: SearchBody,
    _: AuthedUser | None = Depends(rate_limit_or_auth),
):
    """Web search via POST (no encoding issues).

    Body: {"q": "c++ language", "provider": "auto", "limit": 10}
    """
    return await _do_search(
        body.q, body.provider, body.limit,
        body.categories, body.time_range, body.language,
    )
