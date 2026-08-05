"""Source protocol — each platform implements this interface."""

from __future__ import annotations

from typing import Protocol


class FeedSource(Protocol):
    """A source that can fetch a feed (list of posts) for a handle/blog."""

    async def fetch_feed(self, handle: str, *, limit: int = 20) -> tuple[list, str]:
        """Return (posts, source_tag). Raises on total failure."""
        ...


class PostSource(Protocol):
    """A source that can fetch a single post by URL or ID."""

    async def fetch_post(self, identifier: str) -> tuple[object, str]:
        """Return (post, source_tag). Raises on failure."""
        ...
