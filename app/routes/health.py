"""Health + ops endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import AuthedUser
from app.config import settings
from app.instances import get_instances
from app.ratelimit import rate_limit_or_auth
from app.storage import archive_enabled

router = APIRouter()


@router.get("/health")
async def health():
    """Liveness + config snapshot. Open (no auth) for docker healthcheck."""
    return {
        "status": "ok",
        "engine": settings.engine,
        "browser_enabled": settings.browser_enabled,
        "archive_enabled": archive_enabled(),
        "allow_public": settings.allow_public,
        "auth_required": not settings.allow_public and bool(settings.api_keys_set),
    }


@router.get("/instances")
async def instances(_: AuthedUser | None = Depends(rate_limit_or_auth)):
    """Cached Nitter instance list."""
    return {"instances": await get_instances()}
