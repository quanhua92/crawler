"""Archive routes — read-only access to S3-stored responses.

Mirrors the live route paths but reads from S3 instead of fetching.
Like Google Cache: when the source is down, the archive still has it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import AuthedUser
from app.ratelimit import rate_limit_or_auth
from app.storage import archive_enabled, get_archived, get_archived_version, get_archived_versions

router = APIRouter(prefix="/archive", tags=["archive"])


def _require_archive():
    if not archive_enabled():
        raise HTTPException(503, "S3 archive not configured (set CRAWLER_S3_ENDPOINT)")


async def _read(platform: str, kind: str, identifier: str, version: str | None):
    _require_archive()
    if version:
        resp = await get_archived_version(platform, kind, identifier, version)
    else:
        resp = await get_archived(platform, kind, identifier)
    if resp is None:
        raise HTTPException(404, f"not archived: {platform}/{kind}/{identifier}")
    return resp


@router.get("/url/{target:path}")
async def archive_url(
    target: str,
    _: AuthedUser | None = Depends(rate_limit_or_auth),
    version: str | None = Query(None),
):
    if not target.startswith("http"):
        target = f"https://{target}"
    return await _read("url", "fetch", target, version)


@router.get("/x/{handle}")
async def archive_x_feed(
    handle: str,
    _: AuthedUser | None = Depends(rate_limit_or_auth),
    version: str | None = Query(None),
):
    return await _read("x", "feed", handle.lstrip("@"), version)


@router.get("/x/status/{tweet_id}")
async def archive_x_post(
    tweet_id: str,
    _: AuthedUser | None = Depends(rate_limit_or_auth),
    version: str | None = Query(None),
):
    return await _read("x", "post", tweet_id, version)


@router.get("/x/status/{tweet_id}/thread")
async def archive_x_thread(
    tweet_id: str,
    _: AuthedUser | None = Depends(rate_limit_or_auth),
    version: str | None = Query(None),
):
    return await _read("x", "thread", tweet_id, version)


@router.get("/substack/{blog}")
async def archive_substack_feed(
    blog: str,
    _: AuthedUser | None = Depends(rate_limit_or_auth),
    version: str | None = Query(None),
):
    return await _read("substack", "feed", blog.lstrip("@"), version)


@router.get("/substack/{blog}/p/{slug}")
async def archive_substack_post(
    blog: str,
    slug: str,
    _: AuthedUser | None = Depends(rate_limit_or_auth),
    version: str | None = Query(None),
):
    blog = blog.lstrip("@")
    if "." not in blog:
        blog = f"{blog}.substack.com"
    return await _read("substack", "post", f"{blog}/p/{slug}", version)


@router.get("/x/{handle}/versions")
async def archive_x_feed_versions(
    handle: str,
    _: AuthedUser | None = Depends(rate_limit_or_auth),
):
    _require_archive()
    versions = await get_archived_versions("x", "feed", handle.lstrip("@"))
    return {"versions": versions}
