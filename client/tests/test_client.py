"""Tests for crawler-client. Run against a live crawler instance.

    CRAWLER_URL=http://localhost:8321 CRAWLER_KEY=sk-xxx pytest client/tests/ -v
"""

from __future__ import annotations

import os

import pytest

from crawler_client import (
    AuthenticationError,
    CrawlerClient,
    CrawlResponse,
    Post,
    SyncCrawlerClient,
)
from crawler_client.models import Author

BASE = os.environ.get("CRAWLER_URL", "http://localhost:8321")
KEY = os.environ.get("CRAWLER_KEY", "sk-dev-key-change-me")


# ─── Model tests (pure, no network) ────────────────────────────


def test_post_from_dict():
    p = Post.model_validate({
        "id": "123", "platform": "x", "url": "https://x.com/a/status/123",
        "text": "hello", "author": {"username": "alice", "name": "Alice"},
        "metrics": {"favorite_count": 42},
        "media": [{"type": "photo", "url": "https://example.com/a.jpg"}],
    })
    assert p.id == "123"
    assert p.author.username == "alice"
    assert p.author.name == "Alice"
    assert p.metrics["favorite_count"] == 42
    assert len(p.media) == 1
    assert p.media[0].type == "photo"


def test_crawl_response_posts_property():
    resp = CrawlResponse.model_validate({
        "status": "ok", "items": [
            {"id": "1", "platform": "x", "text": "a"},
            {"id": "2", "platform": "x", "text": "b"},
        ],
    })
    assert len(resp.posts) == 2
    assert resp.ok
    assert not resp.failed


def test_crawl_response_single_item():
    resp = CrawlResponse.model_validate({
        "status": "ok", "item": {"id": "1", "platform": "x", "text": "hello"},
    })
    assert len(resp.posts) == 1
    assert resp.posts[0].text == "hello"


def test_crawl_response_empty():
    resp = CrawlResponse.model_validate({"status": "failed", "error": "nothing"})
    assert resp.posts == []
    assert resp.failed
    assert not resp.ok


def test_author_from_dict():
    a = Author.model_validate({"username": "bob"})
    assert a.username == "bob"
    assert a.id is None


# ─── Sync client tests (live) ──────────────────────────────────


@pytest.fixture
def sync_client():
    with SyncCrawlerClient(BASE, key=KEY) as c:
        yield c


def test_sync_health(sync_client):
    h = sync_client.health()
    assert h["status"] == "ok"


def test_sync_auth_error():
    with SyncCrawlerClient(BASE, key="wrong-key") as c:
        with pytest.raises(AuthenticationError):
            c.get_x_feed("QwenDevs")


def test_sync_x_feed(sync_client):
    resp = sync_client.get_x_feed("QwenDevs", limit=3)
    assert resp.ok
    assert len(resp.posts) > 0
    assert resp.posts[0].platform == "x"


def test_sync_x_post(sync_client):
    resp = sync_client.get_x_post("2084102417885585597")
    assert resp.ok
    assert resp.item is not None
    assert resp.item.author.username == "QwenDevs"


def test_sync_substack_feed(sync_client):
    resp = sync_client.get_substack_feed("platformer", limit=3)
    assert resp.ok
    assert len(resp.posts) > 0
    assert resp.posts[0].platform == "substack"


def test_sync_substack_comments(sync_client):
    resp = sync_client.get_substack_comments(
        "platformer", "why-platformer-is-leaving-substack", limit=3,
    )
    assert resp.ok
    assert len(resp.posts) > 0


def test_sync_fetch_url(sync_client):
    resp = sync_client.fetch_url("https://example.com")
    assert resp.ok
    assert resp.item is not None
    assert "Example Domain" in (resp.item.title or "")


def test_sync_instances(sync_client):
    insts = sync_client.instances()
    assert len(insts) > 0
    assert insts[0] == "nitter.net"


# ─── Async client tests (live) ─────────────────────────────────


@pytest.mark.asyncio
async def test_async_x_feed():
    async with CrawlerClient(BASE, key=KEY) as c:
        resp = await c.get_x_feed("QwenDevs", limit=3)
        assert resp.ok
        assert len(resp.posts) > 0


@pytest.mark.asyncio
async def test_async_x_post():
    async with CrawlerClient(BASE, key=KEY) as c:
        resp = await c.get_x_post("2084102417885585597")
        assert resp.ok
        assert resp.item is not None


@pytest.mark.asyncio
async def test_async_health():
    async with CrawlerClient(BASE, key=KEY) as c:
        h = await c.health()
        assert h["status"] == "ok"
