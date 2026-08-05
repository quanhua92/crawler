"""SearXNG search provider — queries a self-hosted SearXNG instance.

SearXNG aggregates 70+ search engines (Google, Bing, DDG, etc.) and returns
JSON results via its /search?format=json API.
"""

from __future__ import annotations

import logging

from app.config import settings
from app.sources.search.base import normalize_result

logger = logging.getLogger("crawler.search.searxng")


async def search(
    query: str,
    *,
    limit: int = 10,
    categories: str = "general",
    time_range: str | None = None,
    language: str | None = None,
) -> tuple[list, str, list[str]]:
    """Query SearXNG. Returns (posts, source_tag, warnings).

    Raises on connection failure (caller catches for DDG fallback).
    """
    import httpx

    base = settings.searxng_url.rstrip("/")
    if not base:
        raise RuntimeError("CRAWLER_SEARXNG_URL not configured")

    params: dict = {
        "q": query,
        "format": "json",
        "categories": categories,
    }
    if time_range:
        params["time_range"] = time_range
    if language:
        params["language"] = language

    warnings: list[str] = []
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.get(f"{base}/search", params=params)
        if resp.status_code != 200:
            raise RuntimeError(
                f"SearXNG returned HTTP {resp.status_code}"
            )
        data = resp.json()

    raw_results = data.get("results", [])[:limit]
    posts = []
    for r in raw_results:
        posts.append(normalize_result(
            url=r.get("url", ""),
            title=r.get("title", ""),
            body=r.get("content", ""),
            engine=r.get("engine", ""),
            score=r.get("score"),
            category=r.get("category", categories),
            source_prefix="search",
        ))

    if data.get("suggestions"):
        warnings.append(f"suggestions: {', '.join(data['suggestions'][:3])}")

    engine_count = len({r.get("engine") for r in raw_results})
    logger.info("searxng returned %d results from %d engines", len(posts), engine_count)
    return posts, "search:searxng", warnings
