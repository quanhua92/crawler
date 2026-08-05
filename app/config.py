"""Application settings, loaded from environment (CRAWLER_* prefix)."""

from __future__ import annotations

import secrets
import sys

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CRAWLER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Auth ----
    api_keys: str = ""  # comma-separated
    allow_public: bool = False
    session_secret: str = ""  # auto-generated if empty
    session_cookie_name: str = "crawler_session"
    session_ttl: int = 7 * 24 * 3600  # 7 days, seconds

    # ---- Rate limits ----
    public_rate_limit: str = "10/minute"  # "<n>/<second|minute|hour|day>"
    authed_rate_limit: str = ""  # empty = unlimited

    # ---- Browser tier (Tier-2) ----
    engine: str = "camoufox"  # camoufox | patchright
    browser_pool_size: int = 2
    browser_enabled: bool = True
    proxy: str = ""  # e.g. http://user:pass@host:port

    # ---- HTTP (Tier-1) ----
    http_timeout: float = 30.0
    user_agent: str = "crawler/0.1 (+https://github.com/quanhua92/crawler)"

    # ---- Nitter instance discovery ----
    instance_cache_ttl: int = 3600  # seconds

    # ---- SearXNG (metasearch for /search endpoint) ----
    # Internal URL. If empty/unset, /search falls back to DuckDuckGo.
    searxng_url: str = "http://searxng:8080"

    # ---- S3 archive (RustFS / MinIO / any S3-compatible) ----
    # When s3_endpoint is empty, archiving is disabled (no-op). Live endpoints
    # write-through to S3 on every fetch; /archive/* routes read from S3 only.
    s3_endpoint: str = ""  # e.g. http://rustfs:9000
    s3_bucket: str = "crawler"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"

    @property
    def api_keys_set(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    @property
    def effective_session_secret(self) -> str:
        if self.session_secret:
            return self.session_secret
        # Auto-generate for dev. Warns; sessions invalidate on restart.
        return _INSECURE_DEV_SECRET


_INSECURE_DEV_SECRET = secrets.token_hex(32)

settings = Settings()


def warn_insecure_config() -> None:
    """Call once at startup to surface config issues."""
    if not settings.session_secret:
        print(
            "WARNING: CRAWLER_SESSION_SECRET not set — using an auto-generated "
            "dev secret. Browser sessions will invalidate on every restart. "
            "Set CRAWLER_SESSION_SECRET for stable sessions.",
            file=sys.stderr,
        )
    if not settings.api_keys_set and not settings.allow_public:
        print(
            "ERROR: Set CRAWLER_API_KEYS to enable auth, or "
            "CRAWLER_ALLOW_PUBLIC=true for open rate-limited mode.",
            file=sys.stderr,
        )
        raise SystemExit(1)
