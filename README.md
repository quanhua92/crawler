# crawler

A self-hostable, **best-effort** content fetcher for X (Twitter), Substack, and any URL.
FastAPI service, Docker-first. Bring your own keys, run it behind your gateway.

> **Best-effort, not guaranteed.** Every response carries provenance
> (`source`, `engine_used`, `status`) so you always know what actually served it.
> See [docs/DESIGN.md](docs/DESIGN.md) for the reasoning behind every choice.

## Quick start

```bash
git clone https://github.com/quanhua92/crawler.git
cd crawler
echo "CRAWLER_API_KEYS=sk-$(openssl rand -hex 16)" >> .env
docker compose pull && docker compose up -d

# API use (Bearer header)
KEY=$(grep CRAWLER_API_KEYS .env | cut -d= -f2)
curl -H "Authorization: Bearer $KEY" "http://localhost:8321/x/QwenDevs?limit=3"
```

Or open `http://localhost:8321/auth` in a browser and paste the key for an interactive cookie session.

To build locally instead of pulling from GHCR: comment out `image:` in `docker-compose.yml`, uncomment `build: .`, then `docker compose up -d --build`.

Without Docker:

```bash
pip install -e ".[dev]"
python -m camoufox fetch && patchright install chromium   # ~300MB browser binaries
uvicorn app.main:app --port 8321 --reload
```

## What it does

- **X feeds** via Nitter RSS (multi-instance fallback, `nitter.net` first, dynamic discovery)
- **X single posts + threads** via Twitter syndication JSON (Nitter-independent)
- **Substack feeds + posts** via public RSS
- **Any URL** via the `/url/...` catch-all — auto-dispatches known hosts, best-effort otherwise
- **Browser fallback** (Camoufox + Patchright) for Cloudflare/antibot-protected sources

## Auth

Two front doors, same key. Service refuses to start if neither `CRAWLER_API_KEYS` nor `CRAWLER_ALLOW_PUBLIC=true` is set.

| Request brings | `ALLOW_PUBLIC=false` (default) | `ALLOW_PUBLIC=true` |
|---|---|---|
| `Authorization: Bearer <key>` | ✅ unlimited | ✅ unlimited |
| Signed cookie (from `/auth`) | ✅ unlimited | ✅ unlimited |
| (anonymous) | `401` | ✅ rate-limited (default `10/minute` per IP) |

- **API clients:** send `Authorization: Bearer <key>` on every request.
- **Browser users:** visit `/auth`, paste a key, get an HttpOnly signed cookie (7-day TTL).
- **Rotate keys:** edit `CRAWLER_API_KEYS=old,new`, restart, migrate clients, drop the old.

## Routes

All `GET`, all accept `?limit ?since ?until ?engine=auto|http|browser ?format=json|jsonl|markdown|raw`.

| Path | Purpose |
|---|---|
| `/url/{target:path}` | any URL, best-effort (auto-dispatch by host) |
| `/x/{handle}` | X user feed (≤20 RSS, >20 browser) |
| `/x/status/{id}` | single X post |
| `/x/status/{id}/thread` | X reply chain (upward) |
| `/x/status/{id}/replies` | X replies to a post (browser) |
| `/substack/{blog}` | Substack feed |
| `/substack/{blog}/p/{slug}` | Substack post |
| `/substack/{blog}/p/{slug}/comments` | Substack post comments (public API) |
| `GET /auth` · `POST /auth` | browser login |
| `/archive/url/{target}` · `/archive/x/{handle}` · etc. | S3 archive (read-only) |
| `/health` · `/instances` | ops |

Examples:

```bash
curl -H "Authorization: Bearer $KEY" http://localhost:8321/x/status/2084102417885585597
curl -H "Authorization: Bearer $KEY" "http://localhost:8321/url/https://nitter.net/QwenDevs/rss"
curl -H "Authorization: Bearer $KEY" "http://localhost:8321/substack/lennysnewsletter?limit=5"
```

## Environment

| Var | Default | Purpose |
|---|---|---|
| `CRAWLER_API_KEYS` | — | comma-separated valid keys; required unless `ALLOW_PUBLIC=true` |
| `CRAWLER_ALLOW_PUBLIC` | `false` | admit anonymous traffic under the rate limit |
| `CRAWLER_SESSION_SECRET` | *(auto)* | itsdangerous cookie-signing secret |
| `CRAWLER_SESSION_TTL` | `604800` | cookie lifetime, seconds (7 days) |
| `CRAWLER_PUBLIC_RATE_LIMIT` | `10/minute` | in-memory limiter for anonymous |
| `CRAWLER_ENGINE` | `camoufox` | browser backend: `camoufox` or `patchright` |
| `CRAWLER_BROWSER_POOL_SIZE` | `2` | warm browser contexts |
| `CRAWLER_BROWSER_ENABLED` | `true` | set `false` to skip the browser tier (saves ~300MB) |
| `CRAWLER_PROXY` | — | proxy URL for the browser tier (sticky/ISP recommended) |
| `CRAWLER_HTTP_TIMEOUT` | `30` | Tier-1 request timeout, seconds |
| `CRAWLER_INSTANCE_CACHE_TTL` | `3600` | Nitter instance list cache, seconds |
| `CRAWLER_S3_ENDPOINT` | `http://rustfs:9000` | S3-compatible endpoint for archive |
| `CRAWLER_S3_BUCKET` | `crawler` | S3 bucket name |
| `CRAWLER_S3_ACCESS_KEY` | `rustfsadmin` | S3 access key |
| `CRAWLER_S3_SECRET_KEY` | `rustfsadmin` | S3 secret key |

## Engines & proxies

- **Tier-1** (`httpx` + `feedparser`) handles `nitter.net`, syndication JSON, Substack — **no proxy ever needed**.
- **Tier-2** (browser) is the fallback when Cloudflare/antibot blocks Tier-1. From a residential IP (your home machine), no proxy needed. From a datacenter IP (VPS), add a sticky or ISP proxy via `CRAWLER_PROXY` — rotating proxies invalidate the `cf_clearance` cookie and force re-solving every request.

## Response shape

```json
{
  "status": "ok",
  "source": "nitter:nitter.net",
  "engine_used": "http",
  "items": [
    { "id": "2084102417885585597", "platform": "x", "url": "https://x.com/QwenDevs/status/2084102417885585597",
      "text": "git init qwen_devs ...", "author": { "username": "QwenDevs", "name": "Qwen Developers" },
      "created_at": "2026-08-03T02:21:51Z", "metrics": { "favorite_count": 396 }, "media": [], "urls": [] }
  ],
  "warnings": [],
  "error": null
}
```

`status` is `ok` (`200`), `partial` (`200`, degraded — some data returned, some failed), or `failed` (`502` — nothing usable after all fallbacks).

## S3 archive (write-through)

Every live request persists to S3 (RustFS): `{hash}/output.json` (latest good) + `{hash}/versions/{ts}.json` (every fetch). Read archived content via `/archive/...` — mirrors the live routes (e.g. `/archive/x/QwenDevs`, `/archive/url/https://...`). Like Google Cache: when the source is down, the archive still has it. Set `CRAWLER_S3_ENDPOINT=""` to disable.

## License

MIT. See [LICENSE](LICENSE).
