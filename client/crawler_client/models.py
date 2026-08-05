"""Pydantic models — mirror the crawler server's response schema."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Author(BaseModel):
    id: str | None = None
    username: str = ""
    name: str | None = None


class Media(BaseModel):
    type: str = ""
    url: str = ""
    expanded_url: str | None = None


class Post(BaseModel):
    id: str = ""
    platform: str = ""
    url: str = ""
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
    reply_to: str | None = None
    repost_of: dict | None = None
    source: str = ""


class CrawlResponse(BaseModel):
    status: Literal["ok", "partial", "failed"] = "ok"
    source: str = ""
    engine_used: str = ""
    items: list[Post] | None = None
    item: Post | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None

    @property
    def posts(self) -> list[Post]:
        if self.items:
            return self.items
        return [self.item] if self.item else []

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def failed(self) -> bool:
        return self.status == "failed"
