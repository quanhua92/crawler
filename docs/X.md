# X (Twitter) — usage guide

How to use crawler for X/Twitter content. See [DESIGN.md](DESIGN.md) for architecture decisions.

---

## Quick reference

| What | Endpoint | Engine | Source |
|---|---|---|---|
| Recent posts (≤20) | `GET /x/{handle}?limit=20` | http | Nitter RSS |
| Recent posts (>20) | `GET /x/{handle}?limit=50` | browser | Nitter HTML → x.com fallback |
| Single post | `GET /x/status/{id}` | http | syndication JSON |
| Reply chain (upward) | `GET /x/status/{id}/thread` | http | syndication JSON |
| Replies to a post | `GET /x/status/{id}/replies` | browser | Nitter HTML → x.com fallback |
| Any X URL | `GET /url/https://x.com/...` | auto | platform auto-detect |

All routes accept `?limit`, `?engine=auto|http|browser`, `?format=json|jsonl|markdown`.

---

## 1. Last N posts from an account

### ≤20 posts (fast, no browser needed)

```
GET /x/QwenDevs?limit=10
```

Fetches the Nitter RSS feed (`{instance}/QwenDevs/rss`), rotates across healthy
instances until one returns real items, slices to `limit`.

```bash
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8321/x/QwenDevs?limit=10"
```

Response:
```json
{
  "status": "ok",
  "source": "nitter:nitter.net",
  "engine_used": "http",
  "items": [
    {
      "id": "2084665356703195433",
      "platform": "x",
      "url": "https://nitter.net/shuai_bai_/status/2084665356703195433#m",
      "text": "What does it really mean for an agent to be multimodal-native?...",
      "author": {"username": "shuai_bai_", "name": ""},
      "created_at": "2026-08-04T15:38:46+00:00",
      "repost_of": {"username": "QwenDevs", "id": "2084665356703195433"},
      "source": "nitter:nitter.net"
    }
  ],
  "warnings": [],
  "error": null
}
```

**Why Nitter RSS?** No auth, no API key, no cost. The official X API charges
~$0.005/post read. Nitter RSS is free and returns ~20 recent posts per user.

**Limitation:** RSS only gives the latest ~20. For more, use >20 (below).

### >20 posts (browser tier required)

```
GET /x/QwenDevs?limit=50
```

When `limit > 20`, the browser tier activates automatically:
1. Loads the Nitter profile page (`xcancel.com/QwenDevs` first — browser solves
   its antibot)
2. Scrolls to load more posts
3. Parses `.timeline-item` elements from the rendered HTML
4. Falls back to the next healthy Nitter instance, then x.com GraphQL as last resort

```bash
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8321/x/QwenDevs?limit=50"
```

**Why rotation?** Each Nitter instance is run by a different operator with
their own pool of Twitter accounts. Rotating distributes load and avoids
single-instance rate limits. The browser solves Cloudflare/antibot on instances
that block plain HTTP.

**Why x.com last?** Going to x.com directly exposes your IP to Twitter. Nitter
instances act as a proxy. We only hit x.com when every Nitter instance fails.

---

## 2. Single post

```
GET /x/status/2084102417885585597
```

Fetches via `cdn.syndication.twimg.com/tweet-result?id={id}&token=a` — Twitter's
embed-widget backend. No auth, no antibot, no Nitter dependency.

```bash
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8321/x/status/2084102417885585597"
```

Response includes `metrics.conversation_count` (total replies) even though the
replies themselves aren't included:

```json
{
  "status": "ok",
  "source": "syndication",
  "engine_used": "http",
  "item": {
    "id": "2084102417885585597",
    "text": "git init qwen_devs\n\nREADME.md:\nHey 👋 ...",
    "author": {"username": "QwenDevs", "name": "Qwen Developers"},
    "metrics": {
      "favorite_count": 396,
      "conversation_count": 247
    },
    "media": [{"type": "photo", "url": "https://pbs.twimg.com/..."}]
  }
}
```

**Why syndication JSON?** It's the most reliable single-post source —
Nitter-independent (Nitter instances die), no auth, no antibot. It's the same
endpoint Twitter's own embed widgets use.

### Nitter RSS vs syndication JSON — when to use which

| | Nitter RSS | syndication JSON |
|---|---|---|
| **Used for** | feeds (last ~20 posts) | single post, thread walk |
| **Auth needed** | none | none (`token=a` is dummy) |
| **Format** | RSS XML | JSON |
| **Antibot** | none on nitter.net; Cloudflare on others | none |
| **Nitter dependency** | yes (instance must be alive) | **no** — hits Twitter's CDN directly |
| **Rate limits** | per-instance (operators manage tokens) | generous (public embed endpoint) |
| **Data depth** | text, author, date, retweet marker | text, author, media, metrics, lang, reply count |
| **When it fails** | instance down/suspended | rarely (Twitter CDN is very reliable) |

The syndication endpoint is the backbone for single posts — it's what makes
`GET /x/status/{id}` work reliably even when every Nitter instance is down.
Nitter RSS is for feeds only.

---

## 3. Reply chain (upward — who is this replying to?)

```
GET /x/status/2084665356703195433/thread
```

Walks the `in_reply_to_status_id_str` chain from the given tweet upward to the
root, fetching each parent via syndication JSON. Returns `[newest, ..., root]`.

```bash
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8321/x/status/2084665356703195433/thread"
```

**When to use:** You have a reply and want to see the full conversation context
above it. This is the *parent chain*, not the replies below.

---

## 4. Replies to a post (downward — who replied to this?)

```
GET /x/status/2084102417885585597/replies?limit=50
```

**Requires browser tier** (`CRAWLER_BROWSER_ENABLED=true`). The syndication
endpoint only returns the tweet itself, not its replies.

Flow:
1. Loads the tweet page on xcancel.com first (browser solves WASM antibot)
2. Parses `.timeline-item` elements — each is a reply
3. Falls back through healthy Nitter instances
4. Last resort: x.com GraphQL `TweetDetail` intercept

```bash
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8321/x/status/2084102417885585597/replies?limit=50"
```

**Why browser?** No free HTTP endpoint exposes tweet replies:
- Syndication JSON: only the tweet itself (+ `conversation_count` = total replies)
- Nitter RSS: user feeds only, not conversation replies
- Twitter GraphQL: requires guest tokens (blocked since 2024)
- Nitter HTML pages: return 0 bytes from plain HTTP (only RSS works)

The browser tier solves all of these — it loads the page in a real browser
(Camoufox/Patchright), which runs JS, solves antibot, and renders the HTML
with replies visible.

**What you get:** Each reply as a normalized `Post` with `id`, `text`,
`author`, `created_at`, `source` (e.g. `nitter-browser:xcancel.com`).

---

## 5. Any X URL (catch-all)

```
GET /url/https://x.com/QwenDevs/status/2084102417885585597
GET /url/https://nitter.net/QwenDevs/rss
GET /url/https://twitter.com/elonmusk
```

Auto-detects the platform from the URL host and dispatches to the right source:
- `x.com`, `twitter.com`, `t.co`, `nitter.*`, `xcancel.com` → X source
- `*.substack.com` → Substack source
- Unknown host → generic web fetch

For X URLs: status URLs go to syndication JSON; profile URLs go to Nitter RSS.

---

## Engine selection

| `engine=` | Behavior |
|---|---|
| `auto` (default) | Tier-1 httpx first; browser fallback only if blocked and limit>20 or replies |
| `http` | Tier-1 only (fast, may miss data when Cloudflare blocks) |
| `browser` | Force browser tier (slower, unblocks everything) |

```bash
# Force browser even for a simple feed (useful when all RSS instances are down)
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8321/x/QwenDevs?limit=10&engine=browser"
```

---

## How Nitter instances are discovered

1. At startup (and cached for 1 hour), crawler fetches `status.d420.de/api/v1/instances`
2. Filters to `healthy == true`
3. Forces `nitter.net` first (canonical, best-maintained)
4. For the browser tier, `xcancel.com` is prepended (97% health, browser solves its antibot)

If the status API is unreachable, falls back to a hardcoded list of 9 known instances.

See [DESIGN.md §4](DESIGN.md) for the full Nitter ecosystem analysis.

---

## Data flow diagram

```
GET /x/QwenDevs?limit=10
        │
        ▼
  ┌──────────────┐    limit ≤ 20    ┌─────────────────────────┐
  │  engine=auto ├─────────────────►│ Nitter RSS (Tier-1 httpx)│
  │              │                  │ rotate healthy instances │
  │              │    limit > 20    ├─────────────────────────┤
  │              ├─────────────────►│ Nitter HTML (browser)    │
  │              │                  │ xcancel → nitter.net → … │
  │              │    all fail      ├─────────────────────────┤
  │              └─────────────────►│ x.com GraphQL (browser)  │
  └──────────────┘                  └─────────────────────────┘

GET /x/status/{id}
        │
        ▼
  syndication JSON (Tier-1, no browser needed)
  cdn.syndication.twimg.com/tweet-result?id={id}&token=a

GET /x/status/{id}/replies
        │
        ▼
  browser tier (required)
  xcancel tweet page → parse .timeline-item replies
  → fallback: nitter instances → x.com GraphQL
```

---

## Response envelope

Every response carries provenance (see [DESIGN.md §10](DESIGN.md)):

| Field | What it tells you |
|---|---|
| `status` | `ok` (clean), `partial` (degraded), `failed` (nothing usable) |
| `source` | Which upstream served it: `nitter:nitter.net`, `syndication`, `nitter-browser:xcancel.com`, `xcom-browser` |
| `engine_used` | `http` (Tier-1) or `browser` (Tier-2) |
| `warnings` | Per-instance failures that led to fallback |
| `error` | `null` on success, error message on failure |

---

## Archived content

Every live request is persisted to S3 (see [README §S3 archive](../README.md#s3-archive-write-through)).
Read archived content via the `/archive/x/...` mirror routes:

```bash
# Latest good snapshot
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8321/archive/x/QwenDevs"

# Point-in-time version
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8321/archive/x/QwenDevs?version=1722874800"

# List all archived versions
curl -H "Authorization: Bearer $KEY" \
  "http://localhost:8321/archive/x/QwenDevs/versions"
```
