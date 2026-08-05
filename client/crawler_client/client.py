"""Typed async + sync clients for the crawler service.

Native async via httpx.AsyncClient, native sync via httpx.Client.
Automatic validation via pydantic.

    async with CrawlerClient(...) as c: ...
    with SyncCrawlerClient(...) as c: ...
"""

from __future__ import annotations

import urllib.parse
from typing import Any

import httpx

from crawler_client.exceptions import (
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    ServerError,
)
from crawler_client.models import CrawlResponse


def _check(resp: httpx.Response) -> None:
    if resp.status_code == 401:
        raise AuthenticationError("invalid or missing API key")
    if resp.status_code == 429:
        raise RateLimitError("rate limited", retry_after=_retry_after(resp))
    if resp.status_code == 404:
        raise NotFoundError("not found")
    if resp.status_code >= 500:
        raise ServerError(f"server error {resp.status_code}")
    resp.raise_for_status()


def _retry_after(resp: httpx.Response) -> int | None:
    v = resp.headers.get("Retry-After")
    return int(v) if v and v.isdigit() else None


def _params(**kw: Any) -> dict:
    return {k: v for k, v in kw.items() if v is not None}


def _url_encode(url: str) -> str:
    return urllib.parse.quote(url, safe="")


class CrawlerClient:
    """Async client (httpx.AsyncClient — native async, connection pooling).

        async with CrawlerClient("http://localhost:8321", key="sk-xxx") as c:
            feed = await c.get_x_feed("QwenDevs", limit=10)
    """

    def __init__(self, base_url: str, *, key: str | None = None, timeout: float = 60.0):
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=_headers(key),
            timeout=timeout,
            follow_redirects=True,
        )

    async def __aenter__(self) -> CrawlerClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def _get(self, path: str, **params: Any) -> CrawlResponse:
        resp = await self._client.get(path, params=_params(**params))
        _check(resp)
        return CrawlResponse.model_validate(resp.json())

    async def _get_raw(self, path: str, **params: Any) -> dict:
        resp = await self._client.get(path, params=_params(**params))
        _check(resp)
        return resp.json()

    # ─── X ─────────────────────────────────────────────────────

    async def get_x_feed(
        self, handle: str, *, limit: int = 20, engine: str = "auto",
    ) -> CrawlResponse:
        return await self._get(f"/x/{handle.lstrip('@')}", limit=limit, engine=engine)

    async def get_x_post(self, tweet_id: str, *, engine: str = "auto") -> CrawlResponse:
        return await self._get(f"/x/status/{tweet_id}", engine=engine)

    async def get_x_thread(self, tweet_id: str, *, engine: str = "auto") -> CrawlResponse:
        return await self._get(f"/x/status/{tweet_id}/thread", engine=engine)

    async def get_x_replies(self, tweet_id: str, *, limit: int = 50) -> CrawlResponse:
        return await self._get(f"/x/status/{tweet_id}/replies", limit=limit)

    # ─── Substack ──────────────────────────────────────────────

    async def get_substack_feed(self, blog: str, *, limit: int = 20) -> CrawlResponse:
        return await self._get(f"/substack/{blog.lstrip('@')}", limit=limit)

    async def get_substack_post(self, blog: str, slug: str) -> CrawlResponse:
        return await self._get(f"/substack/{blog.lstrip('@')}/p/{slug}")

    async def get_substack_comments(
        self, blog: str, slug: str, *, limit: int = 50,
    ) -> CrawlResponse:
        return await self._get(f"/substack/{blog.lstrip('@')}/p/{slug}/comments", limit=limit)

    # ─── Generic URL ───────────────────────────────────────────

    async def fetch_url(self, url: str, *, limit: int = 20, engine: str = "auto") -> CrawlResponse:
        return await self._get(f"/url/{_url_encode(url)}", limit=limit, engine=engine)

    # ─── Search ────────────────────────────────────────────────

    async def search(
        self, query: str, *, provider: str = "auto", limit: int = 10,
        categories: str = "general", time_range: str | None = None,
        language: str | None = None,
    ) -> CrawlResponse:
        """Web search via SearXNG (default) or DuckDuckGo (fallback)."""
        resp = await self._client.post("/search", json={
            "q": query, "provider": provider, "limit": limit,
            "categories": categories, "time_range": time_range,
            "language": language,
        })
        _check(resp)
        return CrawlResponse.model_validate(resp.json())

    # ─── Archive ───────────────────────────────────────────────

    async def get_archive(
        self, platform: str, kind: str, identifier: str, *, version: str | None = None,
    ) -> CrawlResponse:
        return await self._get(f"/archive/{platform}/{identifier}", version=version)

    async def get_archive_versions(self, platform: str, kind: str, identifier: str) -> list[str]:
        body = await self._get_raw(f"/archive/{platform}/{identifier}/versions")
        return body.get("versions", [])

    # ─── Ops ───────────────────────────────────────────────────

    async def health(self) -> dict:
        return await self._get_raw("/health")

    async def instances(self) -> list[str]:
        body = await self._get_raw("/instances")
        return body.get("instances", [])


class SyncCrawlerClient:
    """Sync client (httpx.Client — native sync, connection pooling).

        with SyncCrawlerClient("http://localhost:8321", key="sk-xxx") as c:
            feed = c.get_x_feed("QwenDevs", limit=10)
    """

    def __init__(self, base_url: str, *, key: str | None = None, timeout: float = 60.0):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=_headers(key),
            timeout=timeout,
            follow_redirects=True,
        )

    def __enter__(self) -> SyncCrawlerClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self._client.close()

    def _get(self, path: str, **params: Any) -> CrawlResponse:
        resp = self._client.get(path, params=_params(**params))
        _check(resp)
        return CrawlResponse.model_validate(resp.json())

    def _get_raw(self, path: str, **params: Any) -> dict:
        resp = self._client.get(path, params=_params(**params))
        _check(resp)
        return resp.json()

    # ─── X ─────────────────────────────────────────────────────

    def get_x_feed(self, handle: str, *, limit: int = 20, engine: str = "auto") -> CrawlResponse:
        return self._get(f"/x/{handle.lstrip('@')}", limit=limit, engine=engine)

    def get_x_post(self, tweet_id: str, *, engine: str = "auto") -> CrawlResponse:
        return self._get(f"/x/status/{tweet_id}", engine=engine)

    def get_x_thread(self, tweet_id: str, *, engine: str = "auto") -> CrawlResponse:
        return self._get(f"/x/status/{tweet_id}/thread", engine=engine)

    def get_x_replies(self, tweet_id: str, *, limit: int = 50) -> CrawlResponse:
        return self._get(f"/x/status/{tweet_id}/replies", limit=limit)

    # ─── Substack ──────────────────────────────────────────────

    def get_substack_feed(self, blog: str, *, limit: int = 20) -> CrawlResponse:
        return self._get(f"/substack/{blog.lstrip('@')}", limit=limit)

    def get_substack_post(self, blog: str, slug: str) -> CrawlResponse:
        return self._get(f"/substack/{blog.lstrip('@')}/p/{slug}")

    def get_substack_comments(self, blog: str, slug: str, *, limit: int = 50) -> CrawlResponse:
        return self._get(f"/substack/{blog.lstrip('@')}/p/{slug}/comments", limit=limit)

    # ─── Generic URL ───────────────────────────────────────────

    def fetch_url(self, url: str, *, limit: int = 20, engine: str = "auto") -> CrawlResponse:
        return self._get(f"/url/{_url_encode(url)}", limit=limit, engine=engine)

    # ─── Search ────────────────────────────────────────────────

    def search(
        self, query: str, *, provider: str = "auto", limit: int = 10,
        categories: str = "general", time_range: str | None = None,
        language: str | None = None,
    ) -> CrawlResponse:
        """Web search — always POST (no encoding issues)."""
        resp = self._client.post("/search", json={
            "q": query, "provider": provider, "limit": limit,
            "categories": categories, "time_range": time_range,
            "language": language,
        })
        _check(resp)
        return CrawlResponse.model_validate(resp.json())

    # ─── Archive ───────────────────────────────────────────────

    def get_archive(
        self, platform: str, kind: str, identifier: str, *, version: str | None = None,
    ) -> CrawlResponse:
        return self._get(f"/archive/{platform}/{identifier}", version=version)

    def get_archive_versions(self, platform: str, kind: str, identifier: str) -> list[str]:
        body = self._get_raw(f"/archive/{platform}/{identifier}/versions")
        return body.get("versions", [])

    # ─── Ops ───────────────────────────────────────────────────

    def health(self) -> dict:
        return self._get_raw("/health")

    def instances(self) -> list[str]:
        body = self._get_raw("/instances")
        return body.get("instances", [])


def _headers(key: str | None) -> dict[str, str]:
    h = {"Accept": "application/json", "User-Agent": "crawler-client/0.1"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h
