"""URL → platform/source dispatch.

Detects the platform from a URL's host and routes to the right source module.
Used by the /url/{target:path} catch-all.
"""

from __future__ import annotations

import re
from enum import StrEnum
from urllib.parse import urlparse


class Platform(StrEnum):
    X = "x"
    SUBSTACK = "substack"
    WEB = "web"


def detect(url: str) -> Platform:
    """Detect platform from URL host."""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return Platform.WEB

    if any(h in host for h in ("x.com", "twitter.com", "t.co", "nitter.", "xcancel.com")):
        return Platform.X
    if "substack.com" in host:
        return Platform.SUBSTACK
    return Platform.WEB


_STATUS_RE = re.compile(r"/status(?:es)?/(\d+)", re.IGNORECASE)


def extract_status_id(url: str) -> str | None:
    """Extract a numeric tweet ID from any X/Twitter/Nitter status URL."""
    m = _STATUS_RE.search(url)
    return m.group(1) if m else None


def extract_handle(url: str) -> str | None:
    """Extract a handle from an X/Twitter/Nitter profile URL (not a status URL)."""
    if extract_status_id(url):
        return None
    try:
        path = urlparse(url).path.strip("/")
    except Exception:
        return None
    parts = [p for p in path.split("/") if p]
    if parts and parts[0] not in ("home", "search", "explore", "i", "settings"):
        return parts[0].lstrip("@")
    return None
