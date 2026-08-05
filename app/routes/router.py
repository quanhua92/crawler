"""Generic catch-all: /url/{target:path} — any URL, best-effort.

Auto-detects platform from the URL host and dispatches to the right source.
For unknown hosts, does a generic web fetch.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from app.auth import AuthedUser
from app.models import CrawlResponse
from app.ratelimit import rate_limit_or_auth
from app.registry import Platform, detect, extract_handle, extract_status_id
from app.sources import web as web_src
from app.sources.x import nitter as nitter_src
from app.sources.x import syndication as syndication_src
from app.storage import persist

logger = logging.getLogger("crawler.routes.url")

router = APIRouter(tags=["url"])


@router.get("/url/{target:path}")
async def url_catchall(
    target: str,
    _: AuthedUser | None = Depends(rate_limit_or_auth),
    limit: int = Query(20, ge=1, le=100),
    engine: str = Query("auto"),
    format: str = Query("json"),
):
    """Any URL → auto-detect platform → best-effort fetch."""
    # Normalize: the path may or may not include the scheme
    if not target.startswith("http"):
        target = f"https://{target}"

    platform = detect(target)
    warnings: list[str] = []

    if platform == Platform.X:
        # Is it a status URL?
        status_id = extract_status_id(target)
        if status_id:
            try:
                post = await syndication_src.fetch_tweet(status_id)
                if post:
                    resp = CrawlResponse.ok(item=post, source="syndication", engine="http")
                else:
                    resp = CrawlResponse.failed(error=f"tweet {status_id} not found")
                await persist("url", "fetch", target, {"engine": engine}, resp)
                return resp
            except Exception as e:
                resp = CrawlResponse.failed(error=f"{type(e).__name__}: {e}")
                await persist("url", "fetch", target, {"engine": engine}, resp)
                return resp

        # Or a profile URL?
        handle = extract_handle(target)
        if handle:
            try:
                posts, source, warnings = await nitter_src.fetch_feed(handle, limit=limit)
                if posts:
                    resp = CrawlResponse.ok(
                        items=posts, source=source,
                        engine="http", warnings=warnings,
                    )
                else:
                    resp = CrawlResponse.failed(error="no items", warnings=warnings)
                await persist("url", "fetch", target, {"engine": engine, "limit": limit}, resp)
                return resp
            except Exception as e:
                resp = CrawlResponse.failed(error=f"{type(e).__name__}: {e}")
                await persist("url", "fetch", target, {"engine": engine}, resp)
                return resp

    elif platform == Platform.SUBSTACK:
        blog = target.removeprefix("https://").removeprefix("http://").split("/")[0]
        from app.sources import substack as substack_src

        try:
            posts, source = await substack_src.fetch_feed(blog, limit=limit)
            if posts:
                resp = CrawlResponse.ok(items=posts, source=source, engine="http")
            else:
                resp = CrawlResponse.failed(error=f"substack {blog} empty")
            await persist("url", "fetch", target, {"engine": engine, "limit": limit}, resp)
            return resp
        except Exception as e:
            resp = CrawlResponse.failed(error=f"{type(e).__name__}: {e}")
            await persist("url", "fetch", target, {"engine": engine}, resp)
            return resp

    # Unknown host → generic web fetch
    try:
        post = await web_src.fetch_url(target)
        resp = CrawlResponse.ok(item=post, source=f"web:{platform.value}", engine="http")
    except Exception as e:
        resp = CrawlResponse.failed(error=f"{type(e).__name__}: {e}")
    await persist("url", "fetch", target, {"engine": engine, "limit": limit}, resp)
    return resp
