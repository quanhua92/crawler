"""Tier-1 HTTP client — shared httpx.AsyncClient with retry/backoff."""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger("crawler.fetch")

_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=settings.http_timeout,
            headers={
                "User-Agent": settings.user_agent,
                "Accept": "application/rss+xml, application/xml, "
                          "text/xml, text/html, application/json, */*",
            },
            follow_redirects=True,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
    _client = None


async def fetch_text(url: str) -> tuple[int, str]:
    """GET url → (status_code, body_text). Raises httpx.RequestError on network failure."""
    client = await get_client()
    resp = await client.get(url)
    return resp.status_code, resp.text


async def fetch_json(url: str) -> dict | None:
    """GET url → parsed JSON dict, or None on non-200/parse failure."""
    client = await get_client()
    resp = await client.get(url)
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except Exception:
        return None


async def fetch_bytes(url: str) -> bytes | None:
    """GET url → raw bytes (for media download). None on failure."""
    client = await get_client()
    resp = await client.get(url)
    if resp.status_code != 200:
        return None
    return resp.content
