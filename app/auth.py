"""Auth: Bearer header (API) + itsdangerous-signed cookie (browser)."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings

_serializer: URLSafeTimedSerializer | None = None


def get_serializer() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        _serializer = URLSafeTimedSerializer(
            settings.effective_session_secret,
            salt="crawler-session",
        )
    return _serializer


def sign_session(key: str) -> str:
    """Sign an API key into a URL-safe timed token for cookie storage."""
    return get_serializer().dumps({"key": key})


def unsign_session(token: str) -> str | None:
    """Verify signature + check expiry. Returns the key, or None if invalid."""
    try:
        data = get_serializer().loads(token, max_age=settings.session_ttl)
        return data.get("key")
    except (BadSignature, SignatureExpired):
        return None


@dataclass
class AuthedUser:
    key: str
    via: str  # "bearer" | "cookie"


def try_auth(request: Request) -> AuthedUser | None:
    """Return AuthedUser if the request carries valid Bearer or cookie auth.
    Returns None otherwise (does not raise)."""
    keys = settings.api_keys_set
    if not keys:
        return None

    # 1. Authorization: Bearer <key>
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        key = auth[7:].strip()
        if key in keys:
            return AuthedUser(key=key, via="bearer")

    # 2. Signed session cookie
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        key = unsign_session(token)
        if key and key in keys:
            return AuthedUser(key=key, via="cookie")

    return None


async def resolve_access(request: Request) -> AuthedUser | None:
    """Single dependency for routes: auth + rate-limit.

    Returns AuthedUser if authenticated (unlimited).
    Returns None if anonymous + public mode (already rate-limited by the caller).
    Raises 401 if anonymous + auth required.
    """
    user = try_auth(request)
    if user is not None:
        return user
    if settings.allow_public:
        return None  # anonymous — caller applies rate limit
    raise HTTPException(
        status_code=401,
        detail="authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
