"""Tier-2 browser pool — Camoufox or Patchright (config-switchable).

Used as a fallback when Tier-1 (httpx) is blocked by Cloudflare/antibot.
The browser earns a cf_clearance cookie, which Tier-1 can reuse for ~30min.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import settings

logger = logging.getLogger("crawler.browser")

_pool: list = []  # list of browser contexts
_lock = asyncio.Lock()
_launcher = None  # set by start()


class BrowserUnavailable(Exception):
    """Raised when the browser tier is disabled or fails to start."""


async def start() -> None:
    """Launch and warm the browser pool. Called on FastAPI startup."""
    global _launcher
    if not settings.browser_enabled:
        logger.info("browser tier disabled (CRAWLER_BROWSER_ENABLED=false)")
        return
    engine = settings.engine
    try:
        if engine == "camoufox":
            _launcher = await _start_camoufox()
        elif engine == "patchright":
            _launcher = await _start_patchright()
        else:
            logger.warning("unknown engine %r, defaulting to camoufox", engine)
            _launcher = await _start_camoufox()
        logger.info("browser tier started: %s, pool_size=%d", engine, settings.browser_pool_size)
    except Exception as e:
        logger.warning(
            "browser tier failed to start (%s: %s) — Tier-2 unavailable",
            type(e).__name__, e,
        )
        _launcher = None


async def stop() -> None:
    """Close all browser contexts. Called on FastAPI shutdown."""
    global _launcher, _pool
    for ctx in _pool:
        try:
            await ctx.browser.close()
        except Exception:
            pass
    _pool.clear()
    _launcher = None


async def _start_camoufox():
    from camoufox.async_api import AsyncCamoufox

    proxy = {"server": settings.proxy} if settings.proxy else None

    async def _launch():
        # Camoufox returns a browser instance
        cf = AsyncCamoufox(headless=True, humanize=True, proxy=proxy)
        browser = await cf.__aenter__()
        for _ in range(settings.browser_pool_size):
            ctx = await browser.new_context()
            ctx._cf = cf  # keep ref for cleanup
            _pool.append(ctx)
        return cf

    return await _launch()


async def _start_patchright():
    from patchright.async_api import async_playwright

    pw = await async_playwright().start()
    proxy = {"server": settings.proxy} if settings.proxy else None
    browser = await pw.chromium.launch(headless=True)
    for _ in range(settings.browser_pool_size):
        ctx = await browser.new_context(proxy=proxy if proxy else None)
        ctx._pw = pw
        _pool.append(ctx)
    return browser


async def _acquire():
    """Get a warm browser context from the pool (round-robin)."""
    if not _pool:
        raise BrowserUnavailable("browser pool is empty")
    async with _lock:
        return _pool.pop(0)
    # Note: caller must return via _release


async def _release(ctx) -> None:
    async with _lock:
        _pool.append(ctx)


async def fetch_with_browser(
    url: str, *, wait_for: str = "networkidle", timeout_ms: int = 30000,
) -> str:
    """Navigate to url in a real browser, wait for challenges to clear, return page HTML.

    Solves Cloudflare/antibot challenges natively (the browser runs the JS).
    Raises BrowserUnavailable if the pool is empty.
    """
    ctx = await _acquire()
    try:
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until=wait_for, timeout=timeout_ms)
            # Extra wait for Cloudflare interstitial to resolve
            await asyncio.sleep(3)
            return await page.content()
        finally:
            await page.close()
    finally:
        await _release(ctx)


async def get_cookies(url: str) -> list[dict]:
    """Earn cf_clearance cookies by visiting url, return them for Tier-1 reuse."""
    ctx = await _acquire()
    try:
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)
            return await ctx.cookies()
        finally:
            await page.close()
    finally:
        await _release(ctx)
