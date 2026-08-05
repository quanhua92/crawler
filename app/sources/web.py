"""Generic best-effort web fetch for unknown hosts (the /url fallback)."""

from __future__ import annotations

import re

from app.fetch import fetch_text
from app.models import Author, Post

_TAG_RE = re.compile(r"<[^>]+>")


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


def _extract_text(html: str) -> str:
    # Strip scripts/styles, then tags, collapse whitespace
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.IGNORECASE | re.DOTALL)
    text = _TAG_RE.sub("", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:5000]


async def fetch_url(url: str) -> Post:
    """Best-effort generic fetch. Returns a minimal Post with whatever we got."""
    status, body = await fetch_text(url)
    if status != 200 or not body:
        raise RuntimeError(f"HTTP {status}")

    title = _extract_title(body)
    text = _extract_text(body)

    return Post(
        id=str(abs(hash(url)) % (10**18)),
        platform="web",
        url=url,
        title=title,
        text=text,
        html=body,
        author=Author(username=_domain_of(url)),
        source=f"web:{status}",
    )


def _domain_of(url: str) -> str:
    return re.sub(r"^https?://", "", url).split("/")[0]
