"""Search result normalization — raw dicts → Post objects."""

from __future__ import annotations

import hashlib

from app.models import Post


def normalize_result(
    url: str,
    title: str,
    body: str,
    *,
    engine: str = "",
    score: float | None = None,
    category: str = "",
    source_prefix: str = "search",
) -> Post:
    """Convert a raw search result into a normalized Post."""
    metrics: dict[str, int | float | str] = {}
    if score is not None:
        metrics["score"] = score
    if category:
        metrics["category"] = category

    return Post(
        id=hashlib.sha256(url.encode()).hexdigest()[:20],
        platform="search",
        url=url,
        title=title or "",
        text=body or "",
        source=f"{source_prefix}:{engine}" if engine else source_prefix,
        metrics=metrics,
    )
