"""Substack routes — feeds + posts."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from app.auth import AuthedUser
from app.models import CrawlResponse
from app.ratelimit import rate_limit_or_auth
from app.sources import substack as substack_src
from app.storage import persist

logger = logging.getLogger("crawler.routes.substack")

router = APIRouter(prefix="/substack", tags=["substack"])


@router.get("/{blog}")
async def substack_feed(
    blog: str,
    _: AuthedUser | None = Depends(rate_limit_or_auth),
    limit: int = Query(20, ge=1, le=100),
    format: str = Query("json"),
):
    """Substack blog feed via public RSS."""
    blog = blog.lstrip("@")
    try:
        posts, source = await substack_src.fetch_feed(blog, limit=limit)
    except Exception as e:
        logger.exception("substack feed failed for %s", blog)
        resp = CrawlResponse.failed(error=f"{type(e).__name__}: {e}")
        await persist("substack", "feed", blog, {"limit": limit}, resp)
        return resp

    if posts:
        resp = CrawlResponse.ok(items=posts, source=source, engine="http")
    else:
        resp = CrawlResponse.failed(error=f"substack feed for {blog} not found or empty")

    await persist("substack", "feed", blog, {"limit": limit}, resp)
    return resp


@router.get("/{blog}/p/{slug}")
async def substack_post(
    blog: str,
    slug: str,
    _: AuthedUser | None = Depends(rate_limit_or_auth),
    format: str = Query("json"),
):
    """Single Substack post (fetched via RSS match or direct page)."""
    # v1: search the feed for the slug match
    blog = blog.lstrip("@")
    if "." not in blog:
        blog = f"{blog}.substack.com"

    try:
        posts, source = await substack_src.fetch_feed(blog, limit=50)
    except Exception as e:
        resp = CrawlResponse.failed(error=f"{type(e).__name__}: {e}")
        await persist("substack", "post", f"{blog}/p/{slug}", {}, resp)
        return resp

    match = next((p for p in posts if slug in p.url), None)
    if match:
        resp = CrawlResponse.ok(item=match, source=source, engine="http")
    else:
        resp = CrawlResponse.failed(error=f"post {slug} not found in {blog} feed")

    await persist("substack", "post", f"{blog}/p/{slug}", {}, resp)
    return resp
