"""Pydantic models — unified Post schema + best-effort response envelope."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Author(BaseModel):
    id: str | None = None
    username: str
    name: str | None = None


class Media(BaseModel):
    type: str  # photo | video | animated_gif | audio | embed
    url: str
    expanded_url: str | None = None


class Post(BaseModel):
    """Normalized record, identical shape from every upstream."""

    id: str
    platform: str  # x | substack | web
    url: str
    created_at: datetime | None = None
    author: Author | None = None
    title: str | None = None
    text: str = ""
    html: str | None = None
    lang: str | None = None
    metrics: dict[str, int | float | str] = Field(default_factory=dict)
    media: list[Media] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    quoted: Post | None = None
    reply_to: str | None = None  # parent post id, if a reply
    repost_of: dict | None = None  # {username, id} if a retweet
    # provenance: nitter:nitter.net | syndication | substack-rss | browser:camoufox
    source: str = ""


class CrawlResponse(BaseModel):
    """Best-effort envelope. Every response carries provenance."""

    status: str  # ok | partial | failed
    source: str = ""
    engine_used: str = ""  # http | browser | ""
    items: list[Post] | None = None
    item: Post | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None

    @classmethod
    def ok(cls, *, items=None, item=None, source="", engine="http",
           warnings=None) -> CrawlResponse:
        return cls(status="ok", source=source, engine_used=engine,
                   items=items, item=item, warnings=warnings or [])

    @classmethod
    def partial(cls, *, items=None, item=None, source="", engine="http",
                warnings=None) -> CrawlResponse:
        return cls(status="partial", source=source, engine_used=engine,
                   items=items, item=item, warnings=warnings or [])

    @classmethod
    def failed(cls, *, error: str, source="", engine="",
               warnings=None) -> CrawlResponse:
        return cls(status="failed", source=source, engine_used=engine,
                   error=error, warnings=warnings or [])


Post.model_rebuild()
