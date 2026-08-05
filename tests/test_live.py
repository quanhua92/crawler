"""Live integration tests — real network fetches.

Run all:        pytest tests/test_live.py
Skip live:      pytest -m "not live"
Run only live:  pytest -m live

Targets:
  - Substack: lennysnewsletter.com (public RSS)
  - X feed:   QwenDevs via Nitter RSS
  - X post:   QwenDevs status via syndication JSON
  - Web:      example.com via generic fetch
"""

from __future__ import annotations

import pytest

from app.sources import substack as substack_src
from app.sources import web as web_src
from app.sources.x import nitter as nitter_src
from app.sources.x import syndication as syndication_src

pytestmark = pytest.mark.live

QWEN_STATUS_ID = "2084102417885585597"


# ─── Substack (public RSS — most reliable) ─────────────────────


@pytest.mark.asyncio
async def test_live_substack_feed():
    """Real Substack RSS — lennysnewsletter (custom domain fallback)."""
    posts, source = await substack_src.fetch_feed("lennysnewsletter", limit=3)
    assert len(posts) > 0, "expected at least 1 post from lennysnewsletter"
    assert source == "substack-rss"
    p = posts[0]
    assert p.platform == "substack"
    assert p.url.startswith("http")
    assert len(p.text) > 0 or len(p.html or "") > 0


# ─── X feed via Nitter RSS ─────────────────────────────────────


@pytest.mark.asyncio
async def test_live_x_feed():
    """Real X feed — QwenDevs via Nitter (multi-instance rotation)."""
    posts, source, warnings = await nitter_src.fetch_feed("QwenDevs", limit=3)
    assert len(posts) > 0, f"expected posts from QwenDevs feed (warnings: {warnings})"
    assert source.startswith("nitter:")
    p = posts[0]
    assert p.platform == "x"
    assert p.id  # tweet ID
    assert p.url
    assert len(p.text) > 0


# ─── X single post via syndication JSON ────────────────────────


@pytest.mark.asyncio
async def test_live_x_post():
    """Real X post — QwenDevs first tweet via syndication JSON."""
    post = await syndication_src.fetch_tweet(QWEN_STATUS_ID)
    assert post is not None, "expected tweet from syndication"
    assert post.id == QWEN_STATUS_ID
    assert post.platform == "x"
    assert post.author is not None
    assert post.author.username == "QwenDevs"
    assert "qwen" in post.text.lower() or "git init" in post.text.lower()
    assert post.source == "syndication"


@pytest.mark.asyncio
async def test_live_x_thread():
    """Thread walk via syndication — should return at least 1 post."""
    chain = await syndication_src.fetch_thread(QWEN_STATUS_ID, max_depth=5)
    assert len(chain) >= 1
    assert chain[0].id == QWEN_STATUS_ID


# ─── Generic web fetch ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_live_web_example_com():
    """Generic fetch — example.com."""
    post = await web_src.fetch_url("https://example.com")
    assert post.platform == "web"
    assert "Example Domain" in (post.title or "")
    assert len(post.text) > 0
    assert "example" in post.text.lower()
