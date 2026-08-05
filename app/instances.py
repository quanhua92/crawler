"""Dynamic Nitter instance discovery from status.d420.de.

Fetches the live health list, filters to healthy, forces nitter.net first,
caches for CRAWLER_INSTANCE_CACHE_TTL seconds.
"""

from __future__ import annotations

import logging
import time

import httpx

from app.config import settings

logger = logging.getLogger("crawler.instances")

# Fallback list if the API is unreachable.
_FALLBACK = [
    "nitter.net",
    "nitter.privacyredirect.com",
    "nitter.poast.org",
    "nitter.tiekoetter.com",
    "nitter.kareem.one",
    "nitter.catsarch.com",
    "nuku.trabun.org",
    "lightbrd.com",
    "nitter.space",
]

_cache: list[str] | None = None
_cache_time: float = 0.0
_NITTER_STATUS_URL = "https://status.d420.de/api/v1/instances"


async def get_instances() -> list[str]:
    """Ordered list of healthy Nitter instance hosts, nitter.net forced first."""
    global _cache, _cache_time
    now = time.time()
    if _cache is not None and now - _cache_time < settings.instance_cache_ttl:
        return _cache

    instances = ["nitter.net"]
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.get(_NITTER_STATUS_URL)
            if resp.status_code == 200:
                data = resp.json()
                for host in data.get("hosts", []):
                    if host.get("healthy") and host.get("domain") not in instances:
                        instances.append(host["domain"])
        logger.info("loaded %d nitter instances from status API", len(instances))
    except Exception as e:
        logger.warning("nitter-status API unreachable (%s), using fallback list", e)
        for h in _FALLBACK:
            if h not in instances:
                instances.append(h)

    _cache = instances
    _cache_time = now
    return instances


def invalidate_cache() -> None:
    """Force a refresh on next get_instances() call."""
    global _cache, _cache_time
    _cache = None
    _cache_time = 0.0
