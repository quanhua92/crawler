"""Typed exceptions for crawler-client."""


class CrawlerError(Exception):
    """Base exception."""


class AuthenticationError(CrawlerError):
    """401 — invalid or missing API key."""


class RateLimitError(CrawlerError):
    """429 — rate limited."""

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class NotFoundError(CrawlerError):
    """404 — not found."""


class ServerError(CrawlerError):
    """500/502 — server failure."""
