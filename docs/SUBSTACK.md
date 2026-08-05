# Substack — usage guide

How to use crawler for Substack content. See [DESIGN.md](DESIGN.md) for architecture decisions.

---

## Quick reference

| What | Endpoint | Engine | Source |
|---|---|---|---|
| Blog feed | `GET /substack/{blog}?limit=20` | http | public RSS |
| Single post | `GET /substack/{blog}/p/{slug}` | http | rss match |
| Post comments | `GET /substack/{blog}/p/{slug}/comments` | http | public API |
| Any Substack URL | `GET /url/https://blog.substack.com/...` | auto | platform auto-detect |
| Archived snapshot | `GET /archive/substack/{blog}` | — | S3 read-only |

All routes accept `?limit`, `?format=json|jsonl|markdown`.

---

## 1. Blog feed

```
GET /substack/{blog}?limit=20
```

Fetches the blog's public RSS feed, normalizes each entry to a `Post`.

The `blog` parameter accepts three forms — crawler figures out the right URL:

| Input | Resolved feed URL |
|---|---|
| `platformer` | `https://platformer.substack.com/feed` |
| `platformer.substack.com` | `https://platformer.substack.com/feed` |
| `lennysnewsletter.com` | `https://lennysnewsletter.com/feed` |

```bash
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8000/substack/platformer?limit=5"
```

Response:
```json
{
  "status": "ok",
  "source": "substack-rss",
  "engine_used": "http",
  "items": [
    {
      "id": "...",
      "platform": "substack",
      "url": "https://platformer.substack.com/p/apple-intelligence-iphone-16",
      "title": "Apple's AI strategy is coming into focus",
      "text": "This week's Platformer is free for all readers...",
      "html": "<div>...full content:encoded body...</div>",
      "author": {"username": "casey", "name": "Casey Newton"},
      "created_at": "2026-08-04T12:00:00+00:00",
      "media": [],
      "source": "substack-rss"
    }
  ],
  "warnings": [],
  "error": null
}
```

Each item includes:
- `title` — post headline
- `text` — stripped plain text (first 1000 chars of the body)
- `html` — full `content:encoded` body (the complete post HTML)
- `author` — from `dc:creator`
- `media` — podcast/audio enclosures if present

### Custom-domain blogs (lennysnewsletter, astralcodexten, etc.)

Some Substack blogs migrate to custom domains. When `name.substack.com/feed`
redirects to a profile page (HTML, not RSS), crawler automatically falls back
to `name.com/feed` where the real RSS lives:

```bash
# Lenny uses lennysnewsletter.com — the .substack.com redirect returns HTML
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8000/substack/lennysnewsletter?limit=3"
# → tries lennysnewsletter.substack.com/feed (HTML, not RSS)
# → falls back to lennysnewsletter.com/feed (real RSS)
```

The `_looks_like_rss()` guard ensures we never parse an HTML profile page as
RSS — if the response isn't XML, we try the next URL.

---

## 2. Single post

```
GET /substack/{blog}/p/{slug}
```

Fetches the blog's RSS feed and finds the post matching the slug.

```bash
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8000/substack/platformer/p/apples-ai-strategy"
```

**How it works:** Substack RSS entries have URLs like
`blog.substack.com/p/<slug>`. The route fetches the feed (up to 50 items) and
matches on the slug in the URL. This means only recent posts are available —
older posts that have scrolled off the feed won't be found.

**Limitation:** For historical posts, use `/url/https://blog.substack.com/p/slug`
which does a direct page fetch (generic web source).

---

## 3. Post comments

```
GET /substack/{blog}/p/{slug}/comments?limit=50
```

Fetches comments on a Substack post via Substack's public comment API. No auth,
no browser — plain HTTP.

```bash
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8000/substack/platformer/p/why-platformer-is-leaving-substack/comments?limit=10"
```

**How it works:**
1. Fetches the post page HTML to extract the numeric `post_id`
   (`"post_id":140602898`)
2. Calls `https://{blog}.substack.com/api/v1/post/{post_id}/comments?limit=N`
3. Flattens threaded replies (nested `children`) into a flat list

Each comment is a `Post` with:
- `id` — comment ID
- `text` — stripped comment body
- `html` — raw comment HTML
- `author` — `{username, name}` from the commenter's Substack profile
- `metrics` — `{reaction_count, children_count}` (likes + reply count)
- `reply_to` — parent comment ID (for threading; `null` for top-level)
- `source` — `"substack-comments"`

---

## 4. Any Substack URL (catch-all)

```
GET /url/https://platformer.substack.com/p/some-post
GET /url/https://www.astralcodexten.com/feed
GET /url/https://lennysnewsletter.com/
```

The `/url/{target}` catch-all auto-detects Substack from the host
(`*.substack.com` or known custom domains) and dispatches to the Substack
source. For profile/blog URLs without a specific post, it returns the feed.

```bash
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8000/url/https://platformer.substack.com?limit=5"
```

---

## Why Substack is the easiest source

| Factor | Substack | Compare to X |
|---|---|---|
| Auth needed | none | Nitter instances (volatile) |
| Antibot | none | Cloudflare + WASM PoW |
| Feed format | standard RSS 2.0 | Nitter RSS (depends on instance) |
| Content depth | full `content:encoded` HTML | 280 chars (or threads) |
| Rate limits | none observed | ~300 req/hr per IP |
| Browser tier | never needed | required for replies / >20 posts |

Substack's RSS is clean, public, and complete — every post has its full body
in `content:encoded`, `dc:creator` for authorship, standard `pubDate`, and
`enclosure` tags for podcast episodes. No fallback chain needed.

---

## Data flow

```
GET /substack/platformer?limit=10
        │
        ▼
  ┌──────────────────────────────┐
  │ blog = "platformer"          │
  │ → platformer.substack.com    │
  └──────────┬───────────────────┘
             │
             ▼
  ┌──────────────────────────────┐
  │ GET platformer.substack.com/feed
  │ → 200, RSS XML ✓             │
  └──────────┬───────────────────┘
             │ if HTML (not RSS)
             ▼
  ┌──────────────────────────────┐
  │ Fallback: platformer.com/feed│
  │ → 200, RSS XML ✓             │
  └──────────────────────────────┘


GET /substack/lennysnewsletter?limit=10
        │
        ▼
  ┌──────────────────────────────┐
  │ GET lennysnewsletter.substack.com/feed
  │ → 200, HTML profile page ✗   │  (custom domain redirect)
  └──────────┬───────────────────┘
             │ _looks_like_rss() = false
             ▼
  ┌──────────────────────────────┐
  │ Fallback: lennysnewsletter.com/feed
  │ → 200, RSS XML ✓             │
  └──────────────────────────────┘
```

---

## Response fields

| Field | Type | Notes |
|---|---|---|
| `id` | str | hash of the post URL (Substack uses URL guids) |
| `platform` | `"substack"` | always |
| `url` | str | full post URL |
| `title` | str | post headline |
| `text` | str | plain-text excerpt (first 1000 chars) |
| `html` | str | full `content:encoded` body (complete post) |
| `author` | `{username, name}` | from `dc:creator` |
| `created_at` | ISO datetime | from `pubDate` |
| `media` | `[{type, url}]` | podcast/audio enclosures |
| `source` | `"substack-rss"` | provenance |

---

## Archived content

Every live request persists to S3. Read via `/archive/substack/...`:

```bash
# Latest good snapshot
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8000/archive/substack/platformer"

# Point-in-time version
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8000/archive/substack/platformer?version=1722874800"
```
