# Search — usage guide

Web search via SearXNG (self-hosted metasearch, 70+ engines) with DuckDuckGo fallback (direct, no container needed).

See [DESIGN.md](DESIGN.md) for architecture decisions.

---

## Quick reference

| What | Endpoint | Provider | Container? |
|---|---|---|---|
| Web search | `GET /search?q=...` | auto (searxng → ddg) | SearXNG optional |
| SearXNG only | `GET /search?q=...&provider=searxng` | searxng | required |
| DDG only | `GET /search?q=...&provider=duckduckgo` | duckduckgo | no |

---

## 1. Basic search

```
GET /search?q=python+async+httpx&limit=10
```

```bash
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8321/search?q=python+async+httpx&limit=5"
```

Response:
```json
{
  "status": "ok",
  "source": "search:searxng",
  "engine_used": "http",
  "items": [
    {
      "id": "a3f8b2c1...",
      "platform": "search",
      "url": "https://docs.python.org/3/library/asyncio.html",
      "title": "asyncio — Async IO — Python docs",
      "text": "asyncio is a library to write concurrent code using async/await...",
      "source": "search:google",
      "metrics": {"score": 8.5, "category": "general"}
    }
  ],
  "warnings": [],
  "error": null
}
```

## 2. Provider selection

| `provider=` | Behavior |
|---|---|
| `auto` (default) | Try SearXNG first (70+ engines). If unavailable, fall back to DuckDuckGo. |
| `searxng` | SearXNG only. Fails if SearXNG container is not running. |
| `duckduckgo` | DuckDuckGo only. No container needed — works standalone. |

```bash
# Force DDG (no SearXNG needed)
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8321/search?q=latest+AI+news&provider=duckduckgo&limit=5"
```

## 3. Categories

SearXNG supports multiple categories. DuckDuckGo supports a subset.

| `categories=` | SearXNG | DuckDuckGo | Content |
|---|---|---|---|
| `general` | ✅ | ✅ `.text()` | web pages |
| `news` | ✅ | ✅ `.news()` | news articles |
| `images` | ✅ | ✅ `.images()` | image results |
| `videos` | ✅ | ✅ `.videos()` | video results |
| `it` | ✅ | → general | IT/tech |
| `science` | ✅ | → general | scientific |
| `social media` | ✅ | → general | social posts |
| `files` | ✅ | → general | file downloads |

```bash
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8321/search?q=climate+report&categories=news&limit=10"
```

## 4. Filters

| Param | Default | Values |
|---|---|---|
| `time_range` | *(none)* | `day`, `week`, `month`, `year` (SearXNG only) |
| `language` | *(auto)* | language code: `en`, `vi`, `ja`, ... |

```bash
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8321/search?q=AI+agents&time_range=week&language=en&limit=10"
```

## 5. Python client

```python
from crawler_client import CrawlerClient

async with CrawlerClient("http://localhost:8321", key="sk-xxx") as c:
    results = await c.search("python async", limit=10)
    for post in results.posts:
        print(post.title, post.url)

    news = await c.search("AI news", categories="news", provider="duckduckgo")
    images = await c.search("cats", categories="images")
```

---

## Why SearXNG as default?

| | SearXNG | DuckDuckGo |
|---|---|---|
| **Engines** | 70+ (Google, Bing, DDG, Wikipedia, GitHub, ...) | 1 (DuckDuckGo) |
| **Needs container** | yes (in docker-compose by default) | no |
| **API key** | none | none |
| **Rate limits** | none (self-hosted) | DDG may rate-limit |
| **Privacy** | high (your own instance, no tracking) | medium (queries go to DDG) |
| **Categories** | 7+ | 4 (general, news, images, videos) |
| **Speed** | medium (aggregation overhead) | fast (single source) |

`provider=auto` tries SearXNG first (best results when available), falls back to DDG (always works, zero infra). This matches the crawler's architecture: prefer the richest source, fall back to the most reliable.

## Data flow

```
GET /search?q=python+async&provider=auto
        │
        ▼
  ┌─────────────────────────────────┐
  │ provider=auto                   │
  │   SearXNG healthy?              │
  │   ├─ yes → query SearXNG JSON   │── 70+ engines ──► results
  │   └─ no  → fall through         │
  │   DDG (duckduckgo-search lib)   │── DDG direct ──► results
  └─────────────────────────────────┘
        │
        ▼
  normalize → Post(platform="search") → CrawlResponse
```

---

## Archived search results

Every search query is persisted to S3 like all other endpoints:

```bash
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8321/archive/search/python+async"
```
