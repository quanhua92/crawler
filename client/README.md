# crawler-client

Typed Python SDK for the [crawler](https://github.com/quanhua92/crawler) service.
**Zero dependencies** — stdlib only (urllib + dataclasses). Works anywhere Python 3.11+ runs.

## Install

```bash
pip install git+https://github.com/quanhua92/crawler.git#subdirectory=client
```

## Quick start

```python
from crawler_client import CrawlerClient, SyncCrawlerClient

# Async (FastAPI / asyncio apps)
async with CrawlerClient("http://localhost:8321", key="sk-xxx") as c:
    feed = await c.get_x_feed("QwenDevs", limit=10)
    for post in feed.posts:
        print(post.author.username, post.text[:50])

    post = await c.get_x_post("2084102417885585597")
    replies = await c.get_x_replies("2084102417885585597", limit=20)

# Sync (scripts, notebooks)
with SyncCrawlerClient("http://localhost:8321", key="sk-xxx") as c:
    feed = c.get_x_feed("QwenDevs", limit=10)
    comments = c.get_substack_comments("platformer", "why-platformer-is-leaving-substack")
    any_url = c.fetch_url("https://example.com")
```

## Methods

| Method | Returns |
|---|---|
| `get_x_feed(handle, *, limit=20, engine="auto")` | `CrawlResponse` |
| `get_x_post(tweet_id, *, engine="auto")` | `CrawlResponse` |
| `get_x_thread(tweet_id)` | `CrawlResponse` |
| `get_x_replies(tweet_id, *, limit=50)` | `CrawlResponse` |
| `get_substack_feed(blog, *, limit=20)` | `CrawlResponse` |
| `get_substack_post(blog, slug)` | `CrawlResponse` |
| `get_substack_comments(blog, slug, *, limit=50)` | `CrawlResponse` |
| `fetch_url(url, *, limit=20, engine="auto")` | `CrawlResponse` |
| `get_archive(platform, kind, identifier, *, version=None)` | `CrawlResponse` |
| `get_archive_versions(platform, kind, identifier)` | `list[str]` |
| `health()` | `dict` |
| `instances()` | `list[str]` |

## Error handling

```python
from crawler_client import (
    AuthenticationError,  # 401
    RateLimitError,       # 429
    NotFoundError,        # 404
    ServerError,          # 500/502
    CrawlerError,         # base / network errors
)

try:
    feed = c.get_x_feed("QwenDevs")
except AuthenticationError:
    print("bad API key")
except RateLimitError as e:
    print(f"rate limited, retry after {e.retry_after}s")
```

## Response model

Every method returns `CrawlResponse` with typed dataclass fields:

```python
@dataclass
class CrawlResponse:
    status: str           # "ok" | "partial" | "failed"
    source: str           # "nitter:nitter.net", "syndication", etc.
    engine_used: str      # "http" or "browser"
    items: list[Post] | None
    item: Post | None
    warnings: list[str]
    error: str | None

    @property
    def posts(self) -> list[Post]: ...  # items or [item] or []
    @property
    def ok(self) -> bool: ...
    @property
    def failed(self) -> bool: ...
```

## License

MIT.
