"""Syndication JSON — single X posts via Twitter embed backend.

Endpoint: cdn.syndication.twimg.com/tweet-result?id=<ID>&token=a
No auth, no antibot, no Nitter dependency.
"""

from __future__ import annotations

import logging

from app.fetch import fetch_json
from app.models import Author, Media, Post

logger = logging.getLogger("crawler.x.syndication")


async def fetch_tweet(tweet_id: str) -> Post | None:
    """Fetch a single tweet by numeric ID. Returns None if not found."""
    url = f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&token=a"
    data = await fetch_json(url)
    if not data:
        return None
    return _parse_tweet(data, source="syndication")


async def fetch_thread(tweet_id: str, *, max_depth: int = 50) -> list[Post]:
    """Walk the reply chain upward (newest → oldest root). Returns [newest, ..., root]."""
    chain: list[Post] = []
    current = tweet_id
    seen: set[str] = set()
    while current and current not in seen and len(chain) < max_depth:
        seen.add(current)
        post = await fetch_tweet(current)
        if post is None:
            break
        chain.append(post)
        current = post.reply_to or ""
    return chain


def _parse_tweet(data: dict, source: str = "syndication") -> Post | None:
    if not data or not data.get("id_str"):
        return None

    user = data.get("user", {})
    text = data.get("text", "")

    media: list[Media] = []
    for m in data.get("mediaDetails") or data.get("media", []):
        mtype = m.get("type", "photo")
        media.append(
            Media(
                type=mtype,
                url=m.get("media_url_https", ""),
                expanded_url=m.get("expanded_url"),
            )
        )

    metrics: dict[str, int] = {}
    for k in ("favorite_count", "retweet_count", "reply_count",
              "quote_count", "view_count", "conversation_count"):
        if k in data:
            metrics[k] = data[k]

    quoted = None
    if "quoted_tweet_result" in data:
        inner = data["quoted_tweet_result"].get("result", data["quoted_tweet_result"])
        quoted = _parse_tweet(inner)

    from datetime import datetime

    created_at = None
    raw_dt = data.get("created_at")
    if raw_dt:
        try:
            created_at = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
        except Exception:
            pass

    return Post(
        id=data["id_str"],
        platform="x",
        url=f"https://x.com/{user.get('screen_name', 'i')}/status/{data['id_str']}",
        created_at=created_at,
        author=Author(
            id=user.get("id_str"),
            username=user.get("screen_name", ""),
            name=user.get("name"),
        ),
        text=text,
        lang=data.get("lang"),
        metrics=metrics,
        media=media,
        quoted=quoted,
        reply_to=data.get("in_reply_to_status_id_str"),
        source=source,
    )
