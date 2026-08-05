"""Substack RSS → normalized Post list."""

from __future__ import annotations

import re
from email.utils import parsedate_to_datetime
from html import unescape as _html_unescape

import feedparser

from app.fetch import fetch_text
from app.models import Author, Media, Post

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    text = _TAG_RE.sub("", html)
    return _html_unescape(text).strip()


def parse_feed(xml_text: str, blog: str) -> list[Post]:
    feed = feedparser.parse(xml_text)
    posts: list[Post] = []
    for entry in feed.entries:
        posts.append(_entry_to_post(entry, blog))
    return posts


def _entry_to_post(entry, blog: str) -> Post:
    link = entry.get("link", "") or entry.get("id", "")
    guid = entry.get("id", link) or link
    title = entry.get("title", "")
    description = entry.get("description", "") or entry.get("summary", "")
    creator = (
        entry.get("author")
        or entry.get("creator")
        or entry.get("dc_creator")
        or blog
    )
    content = ""
    contents = entry.get("content", [])
    if contents:
        content = contents[0].get("value", "")

    created_at = None
    pub = entry.get("published") or entry.get("updated")
    if pub:
        try:
            created_at = parsedate_to_datetime(pub)
        except Exception:
            pass

    media: list[Media] = []
    for enc in entry.get("enclosures", []) or []:
        href = enc.get("href") or ""
        if href:
            media.append(Media(type=enc.get("type", "audio").split("/")[0], url=href))

    text_body = _strip_html(description or content)[:1000]

    return Post(
        id=str(hash(guid)),  # Substack guids are URLs; hash for stable short id
        platform="substack",
        url=link,
        created_at=created_at,
        author=Author(username=creator, name=creator),
        title=title,
        text=text_body,
        html=content or description,
        media=media,
        source="substack-rss",
    )


async def fetch_feed(blog: str, *, limit: int = 20) -> tuple[list[Post], str]:
    """Fetch a Substack blog's RSS feed. blog can be 'name' or 'name.substack.com'."""
    blog = blog.lstrip("@").removeprefix("https://").removeprefix("http://").split("/")[0]
    if "." not in blog:
        blog = f"{blog}.substack.com"
    url = f"https://{blog}/feed"
    status, body = await fetch_text(url)
    if status != 200 or not body:
        return [], ""
    posts = parse_feed(body, blog)
    if limit > 0:
        posts = posts[:limit]
    return posts, "substack-rss"
