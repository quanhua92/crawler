"""Tests for normalization logic — nitter RSS, syndication JSON, substack RSS.

Pure-function tests; no network needed. Run: pytest tests/
"""

from __future__ import annotations

from app.registry import Platform, detect, extract_handle, extract_status_id
from app.sources.x.nitter import _strip_html, parse_feed
from app.sources.x.syndication import _parse_tweet
from app.storage import request_hash

# ─── Nitter RSS ───────────────────────────────────────────────

NITTER_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:atom="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0">
  <channel>
    <title>Qwen Developers / @QwenDevs</title>
    <link>https://nitter.net/QwenDevs</link>
    <description>Twitter feed for: @QwenDevs</description>
    <item>
      <title>git init qwen_devs</title>
      <dc:creator>@QwenDevs</dc:creator>
      <description>&lt;p&gt;Hey &amp;#128075; We're the folks from Qwen Foundation Model Team.&lt;/p&gt;</description>
      <pubDate>Sun, 03 Aug 2026 02:21:51 GMT</pubDate>
      <guid>2084102417885585597</guid>
      <link>https://nitter.net/QwenDevs/status/2084102417885585597#m</link>
    </item>
    <item>
      <title>RT by @QwenDevs: What does it really mean?</title>
      <dc:creator>@shuai_bai_</dc:creator>
      <description>&lt;p&gt;What does it really mean for an agent to be multimodal-native?&lt;/p&gt;</description>
      <pubDate>Tue, 04 Aug 2026 15:38:46 GMT</pubDate>
      <guid>2084665356703195433</guid>
      <link>https://nitter.net/shuai_bai_/status/2084665356703195433#m</link>
    </item>
    <item>
      <title>RSS reader not yet whitelisted!</title>
      <dc:creator>@xcancel</dc:creator>
      <description>not whitelisted</description>
      <guid>https://rss.xcancel.com/QwenDevs/rss</guid>
      <link>https://rss.xcancel.com/QwenDevs/rss</link>
    </item>
  </channel>
</rss>"""


def test_nitter_parses_real_tweets():
    posts = parse_feed(NITTER_RSS, "nitter.net")
    # Should skip the non-numeric-guid "not whitelisted" item
    assert len(posts) == 2
    assert posts[0].id == "2084102417885585597"
    assert posts[0].platform == "x"
    assert posts[0].author.username == "QwenDevs"


def test_nitter_strips_html():
    posts = parse_feed(NITTER_RSS, "nitter.net")
    text = posts[0].text
    assert "<p>" not in text
    assert "Hey" in text


def test_nitter_detects_retweet():
    posts = parse_feed(NITTER_RSS, "nitter.net")
    rt = posts[1]
    assert rt.repost_of is not None
    assert rt.repost_of["username"] == "QwenDevs"
    # creator should be the original author
    assert rt.author.username == "shuai_bai_"


def test_nitter_source_tag():
    posts = parse_feed(NITTER_RSS, "nitter.net")
    assert posts[0].source == "nitter:nitter.net"


def test_strip_html_entities():
    assert _strip_html("<p>caf&eacute; &amp; tea</p>") == "café & tea" or "cafe" in _strip_html("<p>caf&eacute;</p>")


# ─── Syndication JSON ─────────────────────────────────────────

SYNDICATION_JSON = {
    "__typename": "Tweet",
    "id_str": "2084102417885585597",
    "text": "git init qwen_devs\n\nREADME.md:\nHey 👋 We're the folks from Qwen Foundation Model Team.",
    "lang": "en",
    "created_at": "2026-08-03T02:21:51.000Z",
    "favorite_count": 396,
    "retweet_count": 42,
    "reply_count": 15,
    "user": {
        "id_str": "2077014085598941184",
        "name": "Qwen Developers",
        "screen_name": "QwenDevs",
    },
    "mediaDetails": [
        {
            "type": "photo",
            "media_url_https": "https://pbs.twimg.com/media/HOw22UFbgAAxcdP.jpg",
            "expanded_url": "https://x.com/QwenDevs/status/2084102417885585597/photo/1",
        }
    ],
}


def test_syndication_parses_tweet():
    post = _parse_tweet(SYNDICATION_JSON)
    assert post is not None
    assert post.id == "2084102417885585597"
    assert post.platform == "x"
    assert post.author.username == "QwenDevs"
    assert post.author.name == "Qwen Developers"
    assert post.lang == "en"
    assert post.metrics["favorite_count"] == 396


def test_syndication_parses_media():
    post = _parse_tweet(SYNDICATION_JSON)
    assert len(post.media) == 1
    assert post.media[0].type == "photo"
    assert "pbs.twimg.com" in post.media[0].url


def test_syndication_url_construction():
    post = _parse_tweet(SYNDICATION_JSON)
    assert "x.com/QwenDevs/status/2084102417885585597" in post.url


# ─── Registry / URL detection ─────────────────────────────────

def test_detect_x_urls():
    assert detect("https://x.com/QwenDevs") == Platform.X
    assert detect("https://twitter.com/elonmusk/status/123") == Platform.X
    assert detect("https://nitter.net/QwenDevs/rss") == Platform.X


def test_detect_substack():
    assert detect("https://lennysnewsletter.substack.com/p/foo") == Platform.SUBSTACK
    assert detect("https://www.substack.com/feed") == Platform.SUBSTACK


def test_detect_unknown():
    assert detect("https://example.com/page") == Platform.WEB


def test_extract_status_id():
    assert extract_status_id("https://x.com/QwenDevs/status/2084102417885585597") == "2084102417885585597"
    assert extract_status_id("https://x.com/QwenDevs") is None


def test_extract_handle():
    assert extract_handle("https://x.com/QwenDevs") == "QwenDevs"
    assert extract_handle("https://nitter.net/elonmusk") == "elonmusk"
    assert extract_handle("https://x.com/QwenDevs/status/123") is None


# ─── Storage hash ─────────────────────────────────────────────

def test_request_hash_deterministic():
    h1 = request_hash("x", "feed", "QwenDevs")
    h2 = request_hash("x", "feed", "QwenDevs")
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_request_hash_different_keys():
    assert request_hash("x", "feed", "QwenDevs") != request_hash("x", "feed", "elonmusk")
    assert request_hash("x", "feed", "QwenDevs") != request_hash("x", "post", "QwenDevs")
    assert request_hash("x", "feed", "QwenDevs") != request_hash("url", "fetch", "QwenDevs")
