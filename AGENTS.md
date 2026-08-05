# AGENTS.md — crawler

Project context for AI agents and contributors. Read this before touching anything.

## What this is

**crawler** is a self-hostable, best-effort content fetcher. It exposes a unified
REST API to fetch X (Twitter) feeds/posts/replies, Substack feeds/posts/comments,
web search (SearXNG + DuckDuckGo), and any URL — all behind one service with auth,
rate limiting, and S3 archiving.

## Architecture

```
crawler/               ← FastAPI service (app/)
├── app/
│   ├── main.py        ← FastAPI app + lifespan (browser pool warm/stop)
│   ├── config.py      ← Settings from CRAWLER_* env vars
│   ├── auth.py        ← Bearer + itsdangerous cookie auth
│   ├── ratelimit.py   ← in-memory token-bucket for anonymous tier
│   ├── models.py      ← pydantic Post + CrawlResponse (shared schema)
│   ├── fetch.py       ← Tier-1: httpx AsyncClient (shared)
│   ├── browser.py     ← Tier-2: Camoufox/Patchright browser pool
│   ├── storage.py     ← S3 write-through archive (RustFS)
│   ├── instances.py   ← dynamic Nitter instance discovery
│   ├── registry.py    ← URL host → platform detection
│   ├── output.py      ← json/jsonl/markdown formatters
│   ├── routes/        ← one file per resource group
│   │   ├── x.py       ← /x/{handle}, /x/status/{id}, /thread, /replies
│   │   ├── substack.py← /substack/{blog}, /p/{slug}, /comments
│   │   ├── search.py  ← GET+POST /search (searxng + ddg)
│   │   ├── router.py  ← /url/{target} catch-all
│   │   ├── archive.py ← /archive/* read-only S3
│   │   ├── auth.py    ← /auth form + cookie
│   │   └── health.py  ← /health, /instances
│   └── sources/       ← one package per platform
│       ├── x/         ← nitter.py, syndication.py, browser.py
│       ├── substack.py
│       ├── search/    ← searxng.py, duckduckgo.py, base.py
│       └── web.py     ← generic URL fetch
├── client/            ← crawler-client SDK (httpx + pydantic)
│   └── crawler_client/
├── searxng/           ← SearXNG settings.yml (JSON API enabled)
├── docs/              ← X.md, SUBSTACK.md, SEARCH.md, DESIGN.md
├── tests/             ← test_normalize.py (unit), test_live.py (network),
│                        test_e2e.py (CLI smoke), conftest.py
├── docker-compose.yml ← crawler + rustfs + searxng + rustfs-init
├── Dockerfile         ← python:3.12-slim + browser deps
└── .github/workflows/ ← ci.yml (lint+test), docker-build-push.yml (ghcr.io)
```

## Two-tier fetch pattern

Every source follows the same pattern:
- **Tier-1** (httpx): fast, stateless, no browser. Primary path.
- **Tier-2** (browser): Camoufox/Patchright fallback for Cloudflare/antibot.

The `engine` query param controls: `auto` (Tier-1 → Tier-2), `http` (Tier-1 only), `browser` (force Tier-2).

## S3 archive pattern

Every live request calls `persist(platform, kind, identifier, params, response)`.
This writes `{hash}/output.json` (latest good) + `{hash}/versions/{ts}.json` (every fetch).
The `/archive/*` routes read from S3 by computing the same hash.

**Critical:** the `(platform, kind, identifier)` tuple must be identical between
persist and archive. If you change one, change both. See the search `+` bug:
path params don't decode `+` to space, query params do — always normalize.

## Search: GET vs POST

`/search` supports both:
- **GET** `/search?q=...` — standard, bookmarkable. URL-encoding handles most queries.
- **POST** `/search` `{"q": "c++ language"}` — no encoding issues for special chars.

The client SDK auto-selects: uses POST when the query contains `+`, `&`, `#`, `"`, or is >1500 chars.

## Environment

All config is via `CRAWLER_*` env vars. See `.env.example` for the full list.
Key defaults: port 8321, engine=camoufox, browser enabled, S3 to internal rustfs.

## Hard rules

- **Never push to git** without explicit user confirmation. Commit only.
- **Always run `ruff check` + `pytest`** before committing. Both must pass.
- **Test against a live service** — use `tests/test_e2e.py` after changes.
- **Save `test_e2e_result.txt`** when updating tests — amend the commit.
- **docker-compose.yml uses `image: ghcr.io`** by default. Uncomment `build: .` for local dev, revert before commit.
- **Port is 8321** everywhere (Dockerfile, compose, README, docs, tests).
- **`metrics` dict accepts `int | float | str`** — search results have category (str) + score (float).
- **ddgs package** (not duckduckgo-search) — the package was renamed.
- **SearXNG JSON API** must be enabled in `searxng/settings.yml` (`formats: [html, json]`).
- **Camoufox needs Firefox deps** in Docker: `libdbus-glib-1-2 libgtk-3-0 libxt6 libxtst6`.

## Verify your changes

```bash
cd crawler
ruff check app/ tests/ client/crawler_client/   # lint
pytest tests/test_normalize.py -q               # unit tests (no network)
pytest tests/ -m "not live" -q                   # all non-live
python tests/test_e2e.py --base http://localhost:8321 --key <key>  # live smoke
```

Full stack: `docker compose up -d --build` (crawler + rustfs + searxng).

## Release

Tag-based: `git tag v0.X.Y && git push origin v0.X.Y`.
Triggers GHCR build at `ghcr.io/quanhua92/crawler:X.Y.Z`.
Uses `GITHUB_TOKEN` (zero secrets). Tags only, not main pushes.
