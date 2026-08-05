"""Nitter RSS → normalized Post list. Multi-instance rotation."""

from __future__ import annotations

import logging
import re
from email.utils import parsedate_to_datetime
from html import unescape as _html_unescape

import feedparser

from app.fetch import fetch_text
from app.instances import get_instances
from app.models import Author, Post

logger = logging.getLogger("crawler.x.nitter")

_RT_RE = re.compile(r"^RT by @(\w+):\s*")
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    """Strip HTML tags and decode entities."""
    text = _TAG_RE.sub("", html)
    return _html_unescape(text).strip()


def parse_feed(xml_text: str, host: str) -> list[Post]:
    """Parse a Nitter RSS XML into Post list. Returns [] for fake/error feeds."""
    feed = feedparser.parse(xml_text)
    posts: list[Post] = []
    for entry in feed.entries:
        guid = str(entry.get("guid", "") or entry.get("id", ""))
        # Skip non-numeric guids (e.g. xcancel "not whitelisted" error items)
        if not guid.isdigit():
            continue
        posts.append(_entry_to_post(entry, host, guid))
    return posts


def _entry_to_post(entry, host: str, guid: str) -> Post:
    title = entry.get("title", "")
    creator = (
        entry.get("creator")
        or entry.get("dc_creator")
        or entry.get("author")
        or ""
    )
    description = entry.get("description", "") or entry.get("summary", "")
    link = entry.get("link", "")
    pub_date = entry.get("published", "")

    text = _strip_html(description) or _strip_html(title)
    repost_of = None
    m = _RT_RE.match(title)
    if m:
        repost_of = {"username": m.group(1), "id": guid}

    created_at = None
    if pub_date:
        try:
            created_at = parsedate_to_datetime(pub_date)
        except Exception:
            pass

    username = creator.lstrip("@")

    # Extract media from description (Nitter embeds <img> and <video> tags)
    media = []
    for img in re.finditer(r'src="(https://pbs\.twimg\.com[^"]+)"', description):
        media.append({"type": "photo", "url": img.group(1)})
    for vid in re.finditer(r'src="(https://video\.twimg\.com[^"]+)"', description):
        media.append({"type": "video", "url": vid.group(1)})

    from app.models import Media

    return Post(
        id=guid,
        platform="x",
        url=link,
        created_at=created_at,
        author=Author(username=username) if username else None,
        text=text,
        html=description,
        media=[Media(**m) for m in media],
        repost_of=repost_of,
        source=f"nitter:{host}",
    )


async def fetch_feed(handle: str, *, limit: int = 20) -> tuple[list[Post], str, list[str]]:
    """Try Nitter instances in order. Returns (posts, source_tag, warnings).

    Stops at the first instance that returns real items.
    """
    handle = handle.lstrip("@")
    instances = await get_instances()
    warnings: list[str] = []

    for host in instances:
        url = f"https://{host}/{handle}/rss"
        try:
            status, body = await fetch_text(url)
            if status != 200 or not body:
                warnings.append(f"{host}: HTTP {status}")
                continue
            posts = parse_feed(body, host)
            if posts:
                if limit > 0:
                    posts = posts[:limit]
                return posts, f"nitter:{host}", warnings
            warnings.append(f"{host}: no items (likely Cloudflare or empty)")
        except Exception as e:
            warnings.append(f"{host}: {type(e).__name__}: {e}")

    return [], "", warnings
