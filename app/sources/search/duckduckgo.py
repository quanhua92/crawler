"""DuckDuckGo search provider — uses duckduckgo-search library.

Works without SearXNG. Handles DDG anti-bot rotation internally.
Supports text, news, images, and videos search.
"""

from __future__ import annotations

import asyncio
import logging

from app.sources.search.base import normalize_result

logger = logging.getLogger("crawler.search.ddg")

_CATEGORY_METHOD = {
    "general": "text",
    "news": "news",
    "images": "images",
    "videos": "videos",
}


async def search(
    query: str,
    *,
    limit: int = 10,
    categories: str = "general",
    time_range: str | None = None,
    language: str | None = None,
) -> tuple[list, str, list[str]]:
    """Query DuckDuckGo via duckduckgo-search. Returns (posts, source_tag, warnings)."""
    method = _CATEGORY_METHOD.get(categories, "text")

    def _do_search():
        from ddgs import DDGS

        with DDGS() as ddgs:
            if method == "text":
                return list(ddgs.text(query, max_results=limit, region=language))
            elif method == "news":
                return list(ddgs.news(query, max_results=limit, region=language))
            elif method == "images":
                return list(ddgs.images(query, max_results=limit))
            elif method == "videos":
                return list(ddgs.videos(query, max_results=limit))
            return []

    try:
        raw = await asyncio.to_thread(_do_search)
    except Exception as e:
        logger.warning("ddg search failed: %s: %s", type(e).__name__, e)
        return [], "", [f"ddg failed: {e}"]

    posts = []
    for r in raw:
        url = r.get("href") or r.get("url") or r.get("image") or ""
        title = r.get("title", "")
        body = r.get("body") or r.get("content") or r.get("description") or ""
        posts.append(normalize_result(
            url=url,
            title=title,
            body=body,
            engine="duckduckgo",
            category=categories,
            source_prefix="search",
        ))

    logger.info("ddg returned %d results", len(posts))
    return posts, "search:ddg", []
