"""In-memory token-bucket rate limiter for the anonymous (public) tier.

Authed users are always exempt (unlimited). When CRAWLER_ALLOW_PUBLIC=true,
anonymous requests are rate-limited per-IP. Single-container default; swap for
a Redis-backed limiter in multi-replica deploys (the .allow(key) interface stays).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict

from fastapi import HTTPException, Request

from app.auth import try_auth
from app.config import settings

_UNIT_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


def _parse_limit(spec: str) -> tuple[int, int]:
    """Parse '<count>/<unit>' → (count, window_seconds). Defaults to 10/60s."""
    try:
        count_str, unit = spec.strip().lower().split("/", 1)
        return int(count_str), _UNIT_SECONDS.get(unit.rstrip("s"), 60)
    except (ValueError, KeyError):
        return 10, 60


class TokenBucket:
    def __init__(self, spec: str) -> None:
        self.rate, self.per = _parse_limit(spec)
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            window = self._buckets[key]
            window[:] = [t for t in window if t > now - self.per]
            if len(window) >= self.rate:
                return False
            window.append(now)
            return True


_bucket = TokenBucket(settings.public_rate_limit)


def reload_bucket() -> None:
    """Recreate the bucket if the rate-limit setting changed (e.g. tests)."""
    global _bucket
    _bucket = TokenBucket(settings.public_rate_limit)


async def rate_limit_or_auth(request: Request):
    """FastAPI dependency: authed → unlimited; anon + public → IP-limited; else 401."""
    user = try_auth(request)
    if user is not None:
        return user  # authed = unlimited

    if not settings.allow_public:
        raise HTTPException(
            status_code=401,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Anonymous + public → rate limit by client IP
    ip = request.client.host if request.client else "unknown"
    if not _bucket.allow(ip):
        raise HTTPException(
            status_code=429,
            detail=f"rate limit exceeded ({settings.public_rate_limit})",
            headers={"Retry-After": str(_bucket.per)},
        )
    return None  # anonymous, admitted
