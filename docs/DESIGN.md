# crawler — design decisions

> The **why** behind crawler. For the **how**, see the [README](../README.md) and the OpenAPI at `/docs` when the service is running.

---

## 1. Goals & non-goals

**Goals**
- Fetch posts and feeds from X (Twitter), Substack, and arbitrary URLs into a single normalized JSON shape.
- Self-hostable, Docker-first, MIT, runnable by anyone.
- Honest about coverage: **best-effort with transparent provenance** — never silent garbage.

**Non-goals (v1)**
- A full Twitter API replacement (no write actions, no DMs, no protected accounts).
- Guaranteed uptime. Nitter instances die; we rotate and degrade gracefully.

---

## 2. Architecture

```
                      ┌─────────────────────────────────────────────┐
                      │              FastAPI on :8321                │
                      │                                             │
   Authorization ─────┼──► verify_auth   (Bearer | itsdangerous)    │
   Cookie ────────────┤         │                                   │
                      │         ▼                                   │
                      │   ┌─────────────┐   tiered_limit            │
                      │   │ try_auth    │   (authed unlimited,      │
                      │   │ AuthedUser? │    anon 10/min in-memory)│
                      │   └──────┬──────┘                           │
                      │          │                                  │
   /url/{target} ─────┼──► registry.py ── host → Source ── dispatch │
   /x/{handle} ───────┤          │                                  │
   /substack/{blog} ──┤          ▼                                  │
                      │   ┌─────────────────┐                       │
                      │   │    Sources      │                       │
                      │   │ x · substack    │                       │
                      │   └──┬──────────┬───┘                       │
                      │      │          │                            │
                      │ ┌────▼────┐ ┌───▼─────────┐                  │
                      │ │ Tier-1  │ │  Tier-2     │                  │
                      │ │ httpx + │ │ Camoufox /  │                  │
                      │ │feedparser│ │ Patchright │                  │
                      │ └────┬────┘ └─────┬───────┘                  │
                      └──────┼────────────┼──────────────────────────┘
                             │            │
                  ┌──────────▼──┐   ┌─────▼──────────────┐
                  │ Nitter RSS  │   │ earn cf_clearance   │
                  │ syndication │   │ → handoff to Tier-1 │
                  │ Substack RSS│   │ for ~30min          │
                  └─────────────┘   └────────────────────┘
```

**Two-tier fetch is the spine.** Tier-1 is fast, stateless, and covers ~90% of requests. Tier-2 is heavy but unblocks antibot-protected sources. The browser earns a `cf_clearance` cookie once, then hands it to Tier-1 so subsequent requests run at httpx speed.

---

## 3. Source choices

| Source | Upstream | Why |
|---|---|---|
| **X feed** | Nitter RSS (multi-instance rotation) | no-auth, no-cost; RSS is clean and parseable |
| **X post / thread** | `cdn.syndication.twimg.com/tweet-result?id=<ID>&token=a` | Nitter-independent escape hatch; clean JSON, no antibot |
| **Substack feed + post** | `<blog>.substack.com/feed` | fully public RSS, no antibot, full `content:encoded` body |

### 3a. Why Nitter for X feeds

Nitter is a privacy front-end that exposes a `/rss` endpoint per user. No Twitter account, no API key, no developer fee. The official X API v2 is pay-per-use (~$0.005/post read) and gated behind approval — overkill for crawling public posts.

The trade-off: Nitter instance health is volatile (see §4), so we **discover instances dynamically** from the nitter-status monitor at `status.d420.de/api/v1/instances`, filter to `healthy==true`, cache for 1 hour, and force `nitter.net` first (the canonical, best-maintained instance). This makes the crawler self-updating as instances come and go.

### 3b. Why syndication JSON for X posts

`cdn.syndication.twimg.com/tweet-result?id=<ID>&token=a` is Twitter's embed-widget backend — the same one used by `<blockquote class="twitter-tweet">` embeds. It returns clean per-tweet JSON (text, author, media, engagement counts) with **no auth, no antibot, and no Nitter dependency**. Single posts bypass everything that makes feeds fragile. Threads walk the `in_reply_to_status_id_str` chain, fetching each parent via the same endpoint.

### 3c. Why Substack is the easiest source

Substack exposes standard RSS at `<blog>.substack.com/feed` — fully public, no antibot, with full `content:encoded` HTML bodies, `dc:creator` authorship, and `enclosure` podcast media. It's the cleanest source in the stack and ships in v1 for free.

---

## 4. The Nitter reality (and why xcancel was rejected)

### The 2024 collapse

On **January 26, 2024**, Twitter killed guest-account creation. Before that, Nitter could mint anonymous guest tokens freely — set-and-forget. After, Nitter operators must inject **real logged-in account tokens** (cookies from burner accounts) into `sessions.jsonl`. When those tokens get rate-limited or suspended, the instance breaks until the operator feeds in fresh ones.

This is why the public Nitter ecosystem collapsed from 50+ instances (pre-2024: snopyta, 1d4.us, kavin.rocks, fdn.fr, unixfox…) down to roughly 10 today, and why instances go stale constantly.

### Live instance census (Aug 2026, from `status.d420.de`)

| Host | Health | Country | From a Python client |
|---|---|---|---|
| **nitter.net** | 95% | 🇳🇱 | ✅ 200, 17 items — **only one reliably serving plain HTTP** |
| xcancel.com | 97% | 🇺🇸 | antibot (WASM proof-of-work) |
| nitter.privacyredirect.com | 90% | 🇫🇮 | Cloudflare JS challenge |
| nitter.poast.org | 86% | 🇺🇸 | connection failed |
| nitter.kareem.one | 91% | 🇸🇬 | Cloudflare JS challenge |
| nitter.catsarch.com | 73% | 🇺🇸/🇩🇪 | `403` |
| nitter.tiekoetter.com | 49% | 🇩🇪 | `403` |
| nuku.trabun.org | 95% | 🇨🇱 | Cloudflare JS challenge |
| nitter.space | 95% | 🇺🇸 | Cloudflare WAF (NSFW/ads) |
| lightbrd.com | 94% | 🇹🇷 | Cloudflare WAF (NSFW) |

"Healthy" + `rss:true` in the monitor **does not mean reachable from Python** — most sit behind Cloudflare. Only `nitter.net` reliably serves a plain HTTP client. This is exactly why we need the browser tier (§5, §6).

### Why xcancel was rejected

xcancel has two surfaces; both are hostile to plain HTTP:

- **RSS** (`rss.xcancel.com/<user>/rss`) is **whitelist-gated**. It returns only a *"RSS reader not yet whitelisted!"* item with a unique ID; you must email `rss@xcancel.com` with the ID + a reason to get your reader whitelisted. The whitelist ID changes on every request (tied to IP/UA fingerprint), so it's a per-reader email exchange, not a stable token. No accounts exist (it's a read-only nitter frontend).
- **Status pages** (`xcancel.com/<user>/status/<id>`) run a **WASM proof-of-work antibot challenge** (`cap_wasm` + fingerprint cookie). Unsolvable from `requests`/`feedparser`; needs a real browser.

The browser tier (§6) *can* solve the xcancel antibot natively, so xcancel can be added as an opt-in source later. It's just not worth the complexity for v1 when `nitter.net` + syndication JSON cover the same ground.

---

## 5. Two-tier fetch

```
   request
      │
      ▼
   ┌──────────────────────────────────────────┐
   │ Tier-1: httpx + feedparser (fast path)   │
   │  • nitter RSS · syndication JSON ·        │
   │    substack RSS · generic HTTP fetch      │
   │  • retry/backoff · instance rotation      │
   └──────────────┬───────────────────────────┘
                  │  blocked? (Cloudflare, antibot, 403)
                  ▼
   ┌──────────────────────────────────────────┐
   │ Tier-2: anti-detect browser (fallback)    │
   │  • Camoufox | Patchright (CRAWLER_ENGINE) │
   │  • pool of warm contexts (lifespan)        │
   │  • navigate → solve challenge → extract   │
   │  • capture cf_clearance cookie            │
   └──────────────┬───────────────────────────┘
                  │  cf_clearance + UA
                  ▼
   ┌──────────────────────────────────────────┐
   │ handoff → Tier-1 reuses cookie ~30min     │
   │ (cf_clearance is IP+UA-bound; expires)    │
   └──────────────────────────────────────────┘
```

**Why two tiers:** the browser is slow (~seconds per solve) and heavy (~300MB Chromium/Firefox), but unblocks antibot. Plain HTTP is fast and light but gets blocked. Tier-1-first means the common case is cheap; Tier-2 only kicks in when Tier-1 is blocked, and the cookie handoff means Tier-2 only needs to run once per ~30 minutes per instance.

The `engine` query param lets callers force the tier: `auto` (default, Tier-1 → Tier-2 fallback), `http` (Tier-1 only), `browser` (force Tier-2).

---

## 6. Why Camoufox + Patchright (config-switchable)

### Why anti-detect, not vanilla Playwright

In 2026, **vanilla Playwright + `playwright-stealth` mostly fails Cloudflare**. Cloudflare's bot score aggregates many signals: `navigator.webdriver`, CDP (Chrome DevTools Protocol) artifacts, TLS/JA3 fingerprint, canvas/WebGL consistency, IP reputation, behavioral timing. Hiding `navigator.webdriver` alone (what stealth plugins do) is no longer enough.

### How anti-detect browsers win

| Technique | What it does | Used by |
|---|---|---|
| **CDP leak elimination** | patches the DevTools Protocol control-plane that bot detectors look for | Patchright, rebrowser |
| **Engine-level fingerprint forging** | modifies browser C++ source so canvas/WebGL/fonts/screen natively report a *coherent* spoofed device (not a JS patch, which is internally inconsistent and detectable) | Camoufox, Donut |
| **BrowserForge profile rotation** | samples (UA, screen, GPU, fonts, timezone) combos from real-world traffic distributions — every context looks like a distinct plausible device | Camoufox |
| **No-WebDriver architecture** | drives Chrome via the raw debugging pipe, abandoning CDP/WebDriver entirely | Nodriver |

### Why both, switchable

| Engine | Strength | Why pick it |
|---|---|---|
| **Camoufox** (default) | 🥇 strongest vs Cloudflare in 2026 benchmarks; Firefox engine has fewer native tells than Chromium; BrowserForge fingerprint rotation | when bypass reliability matters most |
| **Patchright** | drop-in undetected Playwright (same API); Chromium compatibility; easy migration | when a specific site behaves better in Chromium, or for minimal divergence from stock Playwright |

`CRAWLER_ENGINE=camoufox|patchright` flips between them; the `browser.py` pool abstracts both behind one interface.

### Why not commercial anti-detect browsers

Multilogin (~$99/mo), GoLogin, Dolphin Anty, AdsPower are GUI profile-managers for multi-account workflows (ad-fraud, hundreds of social identities). Paid, heavy, wrong shape for a programmatic API service. The open-source Tier-A tools give the same fingerprint quality for free.

### Honest limits

Anti-detect browsers pass **most** Cloudflare pages (~85–95% in 2026 benchmarks), **not any**. They still fail on: interactive Turnstile image challenges (needs a CAPTCHA solver service), WAF rules hard-blocking by IP/ASN regardless of browser, layered second bot-managers (DataDome, Akamai, HUMAN), and bad-IP escalation. This is exactly why the design is Tier-1-first with the browser as fallback, not browser-everywhere.

---

## 7. Proxies (optional, sticky not rotating)

| Run from | Tier-1 needs proxy? | Tier-2 needs proxy? |
|---|---|---|
| **Home / residential ISP** (your Mac) | never | no — your IP is already residential |
| **Datacenter / VPS** (AWS, Hetzner, …) | never | **yes** — datacenter IPs get flagged within a request or two |

The Tier-1 paths (`nitter.net`, syndication JSON, Substack) have no Cloudflare — they never need a proxy regardless of where you run. Only the browser tier benefits from a residential proxy, and only when run from a datacenter IP.

**Use sticky or ISP proxies, not rotating.** The `cf_clearance` cookie is bound to IP + User-Agent and lives ~30 minutes. A rotating proxy (new IP per request) invalidates the cookie constantly → the browser re-solves the challenge every request → slow and expensive. Sticky residential or ISP proxies (static residential, datacenter-hosted under ISP ASNs) hold one IP long enough for the cookie to stay valid.

Default: `CRAWLER_PROXY` unset. Flip it on only if you deploy to a VPS and observe the browser tier getting challenged.

---

## 8. URL design — `/url/{target:path}`

The route surface mirrors the **r.jina.ai pattern**: prefix any URL on a catch-all path (`/url/<url>` like `r.jina.ai/<url>`), plus dedicated tier-1 paths for platforms we've built custom extractors for.

```
GET /url/https://nitter.net/QwenDevs/rss        ← generic catch-all (any URL)
GET /url/https://x.com/QwenDevs/status/123      ← also works (auto-detects X)
GET /x/QwenDevs                                  ← tier-1 custom X feed
GET /substack/lennysnewsletter                   ← tier-1 custom Substack feed
```

**Why path, not query string.** Putting the URL in the path (FastAPI `/url/{target:path}`) reads naturally and matches jina's design. Target URLs containing `?`/`#` must be percent-encoded by the caller (jina has the same constraint).

**Why `/url` beat the alternatives:**
- `/r/` — too cryptic (Reddit? "raw"? "read"?)
- `/public` — collides with the `CRAWLER_ALLOW_PUBLIC` auth-tier concept (same word, two meanings)
- `/custom` — semantically backwards; this is the *generic* path for URLs we *don't* have custom handling for

`/url` is the most literal: "pass a URL, get its content."

The `/url/` catch-all auto-detects the host: `x.com`/`twitter.com`/`nitter.*` → X source, `*.substack.com` → Substack source, unknown host → generic best-effort fetch. Same machinery as the dedicated paths, just one front door.

---

## 9. Auth model

### Tiered access (r.jina.ai free-vs-paid pattern)

| Request brings | `ALLOW_PUBLIC=false` (default) | `ALLOW_PUBLIC=true` |
|---|---|---|
| Valid Bearer or signed cookie | ✅ unlimited | ✅ unlimited |
| Nothing (anonymous) | `401` | ✅ `10/minute` per IP (in-memory limiter) |

Auth is always *accepted*. The toggle only controls whether anonymous traffic is rejected (default, safe) or admitted under a rate limit. **Safe by default**, with an explicit opt-in to openness.

### Two front doors, same key

- **API clients:** `Authorization: Bearer <key>` header on every request. Stateless.
- **Browser users:** `GET /auth` → paste key in a form → `POST /auth` validates against the env key set → sets an HttpOnly + Secure + SameSite=Lax cookie holding a **signed token** → redirect to `/`.

### Why itsdangerous for the cookie

The cookie holds `URLSafeTimedSerializer.dumps({"key": "<key>"})` — an HMAC-signed, timestamped, URL-safe token. On each request, `verify_auth` runs `serializer.loads(cookie, max_age=604800)` (7 days), then **re-checks the bound key against the live `CRAWLER_API_KEYS` set**. Two layers: the signature proves "we issued this," membership proves "it's still current." So rotating a key out of the env invalidates every cookie bound to it instantly, even though the cookie itself is stateless.

`itsdangerous` is tiny (~30KB, no transitive deps), the standard FastAPI/Flask choice for signed sessions, and gives tamper-proofing + expiry for free without a session database.

### Why not store the raw key in the cookie

Cookie theft would leak the raw key. The signed token only proves the key *was* valid at issue time; the live-membership check is what authorizes the current request. Rotating a key out of the env invalidates its cookies without needing a server-side revocation list.

### Rotation

Comma-separated `CRAWLER_API_KEYS=old,new` enables an overlap window: add the new key, restart, migrate clients, drop the old key. Zero-downtime, no `401`s during cutover. Restart-to-rotate keeps the code simple; `docker compose up -d` is a 10-second gap.

---

## 10. Best-effort response envelope

Every response carries explicit provenance so callers branch on what actually happened — never silent garbage:

```json
{
  "status": "ok | partial | failed",
  "source": "nitter:nitter.net",        // what actually served it
  "engine_used": "http | browser",
  "items": [ ... ] | "item": { ... },
  "warnings": [ "nitter.poast.org failed: timeout, fell back" ],
  "error": null | "all sources exhausted: <reason>"
}
```

| HTTP | `status` | Meaning |
|---|---|---|
| `200` | `ok` | Got the requested data cleanly |
| `200` | `partial` | Got *some* data but degraded (fewer items after fallback, media failed, etc.) |
| `502` | `failed` | Tried everything (all Nitter instances + browser tier) and got nothing — `error` explains why |

The service makes **no coverage claims**. It returns what it can fetch and is fully transparent about which upstream served it and what failed. Callers decide whether `partial` is good enough for their use case.

---

## 11. Decision summary

| Decision | Choice | One-line why |
|---|---|---|
| Service shape | FastAPI on `:8321` | matches `ai/` conventions; service not CLI; automate-able |
| X feed source | Nitter RSS, dynamic instance list | no-auth, no-cost; instances volatile so discover dynamically |
| X single post | syndication JSON | Nitter-independent escape hatch |
| Substack | public RSS | trivially available, no antibot |
| Fetch architecture | two-tier (httpx → browser) | fast default + heavy fallback for antibot |
| Browser engine | Camoufox + Patchright, switchable | anti-detect tier; both have edge cases |
| Instance discovery | `status.d420.de/api/v1/instances` | authoritative live list; cache 1h |
| Generic route | `/url/{target:path}` | jina-style; `/url` most literal |
| Auth default | required (never-public by default) | safe-by-default |
| Auth opt-in | `CRAWLER_ALLOW_PUBLIC=true` + 10/min in-memory limiter | r.jina.ai free-tier pattern |
| Auth method | Bearer (API) + itsdangerous cookie (browser) | stateless, rotation-safe |
| Session TTL | 7 days | balanced convenience/security |
| Proxy | optional, sticky/ISP only | Tier-1 never needs one; Tier-2 only from datacenter |
| Response shape | `{status, source, engine_used, ...}` envelope | transparent provenance |
| Packaging | standalone MIT repo, Docker-first | runnable by anyone |

---

## 12. Future

- **Async webhook path** for heavy multi-step fetches (post a job, get a callback) — reserved, not in v1.
- **More sources** — Reddit, Medium, RSS-anywhere. The `sources/` plugin registry makes this additive.
- **Hot-reload auth** — re-read `CRAWLER_API_KEYS` every 30s so rotation needs no restart (matters for k8s secret mounts).
- **Redis-backed limiter** for multi-replica deploys (swap the in-memory token bucket for a Redis-backed one; interface stays the same).
- **Interactive Turnstile** solver integration (CapSolver/2Captcha) for the hardest CF pages.
- **Search** across crawled content (reuse faultline's RAG/Milvus pattern if integrated there).
