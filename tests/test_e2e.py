#!/usr/bin/env python3
"""End-to-end smoke tests for the crawler service.

Runs against a live deployed crawler instance (default localhost:8321).
Each scenario prints a clear [PASS]/[FAIL] with useful detail.

Usage:
    python3 tests/test_e2e.py                              # all scenarios vs localhost:8321
    python3 tests/test_e2e.py --base http://my-host:8321   # vs a deployed URL
    python3 tests/test_e2e.py --key sk-mykey               # with API key
    python3 tests/test_e2e.py --only substack,x-post       # run only these scenarios
    python3 tests/test_e2e.py --skip replies               # skip these

Set CRAWLER_API_KEYS in the target service, or pass --key.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "http://localhost:8321"

_passed = 0
_failed = 0


# ─── HTTP helper ─────────────────────────────────────────────


def request(
    base: str,
    path: str,
    *,
    key: str | None = None,
    timeout: int = 60,
) -> tuple[int, dict | list | str]:
    """GET base+path with optional Bearer key. Returns (status, parsed_body)."""
    url = base.rstrip("/") + path
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    # Print the request being sent
    auth_preview = f"Bearer {key[:8]}..." if key else "(none)"
    print(f"  → GET {url}")
    print(f"    Authorization: {auth_preview}")

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            raw = resp.read().decode()
    except urllib.error.HTTPError as e:
        status = e.code
        raw = e.read().decode()
    except urllib.error.URLError as e:
        return 0, f"connection error: {e.reason}"

    try:
        parsed = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        parsed = raw

    return status, parsed


# ─── Scenario framework ──────────────────────────────────────


def run(name: str, fn, base: str, key: str | None) -> bool:
    """Run a scenario. Returns True if passed."""
    global _passed, _failed
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

    t0 = time.time()
    try:
        fn(base, key)
        elapsed = time.time() - t0
        print(f"  [PASS] {name} ({elapsed:.1f}s)")
        _passed += 1
        return True
    except AssertionError as e:
        elapsed = time.time() - t0
        print(f"  [FAIL] {name} ({elapsed:.1f}s)")
        print(f"         {e}")
        _failed += 1
        return False
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  [FAIL] {name} ({elapsed:.1f}s)")
        print(f"         {type(e).__name__}: {e}")
        _failed += 1
        return False


def _check(condition, msg: str):
    if not condition:
        raise AssertionError(msg)


def _truncate(obj, max_str: int = 80, max_list: int = 5):
    """Walk a JSON tree — truncate long strings, cap list length.
    Keeps the full structure visible so you can see every field."""
    if isinstance(obj, str):
        return obj[:max_str] + "..." if len(obj) > max_str else obj
    if isinstance(obj, dict):
        return {k: _truncate(v, max_str, max_list) for k, v in obj.items()}
    if isinstance(obj, list):
        items = [_truncate(i, max_str, max_list) for i in obj[:max_list]]
        if len(obj) > max_list:
            items.append(f"... ({len(obj)} items total)")
        return items
    return obj


def _show(label: str, obj, max_str: int = 80):
    """Print a JSON object with long fields truncated but structure intact."""
    truncated = _truncate(obj, max_str)
    text = json.dumps(truncated, indent=2, default=str)
    print(f"  {label}:")
    for line in text.split("\n"):
        print(f"    {line}")


# ─── Scenarios ───────────────────────────────────────────────


def s_health(base: str, key: str | None):
    """Health endpoint returns 200 with config snapshot."""
    status, body = request(base, "/health", timeout=5)
    _check(status == 200, f"expected 200, got {status}")
    _check(isinstance(body, dict), "response should be JSON dict")
    _check(body.get("status") == "ok", f"status should be 'ok', got '{body.get('status')}'")
    _show("response", body)


def s_auth_required(base: str, key: str | None):
    """Without auth key, protected routes return 401 (unless allow_public)."""
    if key is None:
        print("  (skipped — no key set, can't verify auth rejection)")
        return
    status, body = request(base, "/x/QwenDevs", key=None, timeout=5)
    _check(
        status in (401, 200),
        f"expected 401 (auth required) or 200 (public mode), got {status}",
    )
    if status == 401:
        print("  auth enforced: 401 without key ✓")
        _show("response", body)
    else:
        print("  public mode: anonymous admitted (CRAWLER_ALLOW_PUBLIC=true)")
        _show("response", body)


def s_auth_page(base: str, key: str | None):
    """/auth returns an HTML login form."""
    status, body = request(base, "/auth", timeout=5)
    _check(status == 200, f"expected 200, got {status}")
    if isinstance(body, str):
        _check("<form" in body.lower() or "input" in body.lower(),
               "expected an HTML form")
    print("  /auth returns HTML login form ✓")


def s_x_feed(base: str, key: str | None):
    """X feed via Nitter RSS returns real posts."""
    status, body = request(base, "/x/QwenDevs?limit=3", key=key)
    _check(status == 200, f"expected 200, got {status}: {body}")
    if isinstance(body, dict):
        _check(body.get("status") in ("ok", "partial"),
               f"status should be ok/partial, got '{body.get('status')}'")
        items = body.get("items") or []
        _check(len(items) > 0, "expected at least 1 post")
        p = items[0]
        _check(p.get("platform") == "x", f"platform should be 'x', got '{p.get('platform')}'")
        _check(bool(p.get("id")), "post should have an id")
        _show("response", body)
    else:
        raise AssertionError(f"expected dict, got {type(body)}")


def s_x_post(base: str, key: str | None):
    """Single X post via syndication JSON."""
    status, body = request(base, "/x/status/2084102417885585597", key=key)
    _check(status == 200, f"expected 200, got {status}")
    if isinstance(body, dict):
        _check(body.get("status") in ("ok", "partial"),
               f"status should be ok/partial, got '{body.get('status')}'")
        item = body.get("item")
        _check(item is not None, "expected item")
        _check(item["author"]["username"] == "QwenDevs",
               f"author should be QwenDevs, got {item['author']['username']}")
        _show("response", body)


def s_x_thread(base: str, key: str | None):
    """Reply chain walk via syndication."""
    status, body = request(base, "/x/status/2084102417885585597/thread", key=key)
    _check(status == 200, f"expected 200, got {status}")
    if isinstance(body, dict):
        items = body.get("items") or []
        _check(len(items) >= 1, "expected at least 1 post in thread")
        _show("response", body)


def s_x_replies(base: str, key: str | None):
    """Replies to a tweet (requires browser tier)."""
    status, body = request(base, "/x/status/2084102417885585597/replies?limit=5", key=key)
    if isinstance(body, dict) and body.get("status") == "failed":
        print(f"  (browser tier may be disabled: {body.get('error', '')[:100]})")
        print("  skipping — not a failure, browser may be off")
        return
    _check(status in (200, 502), f"expected 200/502, got {status}")
    if status == 200 and isinstance(body, dict):
        _show("response", body)


def s_substack_feed_native(base: str, key: str | None):
    """Substack feed — native domain (platformer.substack.com)."""
    status, body = request(base, "/substack/platformer?limit=3", key=key)
    _check(status == 200, f"expected 200, got {status}")
    if isinstance(body, dict):
        items = body.get("items") or []
        _check(len(items) > 0, "expected at least 1 post")
        _check(items[0]["platform"] == "substack", "platform should be substack")
        _show("response", body)


def s_substack_feed_custom(base: str, key: str | None):
    """Substack feed — custom domain fallback (lennysnewsletter)."""
    status, body = request(base, "/substack/lennysnewsletter?limit=3", key=key)
    _check(status == 200, f"expected 200, got {status}")
    if isinstance(body, dict):
        items = body.get("items") or []
        _check(len(items) > 0, "expected at least 1 post (custom domain fallback)")
        _show("response", body)


def s_substack_comments(base: str, key: str | None):
    """Substack post comments via public API."""
    status, body = request(
        base,
        "/substack/platformer/p/why-platformer-is-leaving-substack/comments?limit=3",
        key=key,
    )
    _check(status == 200, f"expected 200, got {status}")
    if isinstance(body, dict):
        items = body.get("items") or []
        _check(len(items) > 0, "expected at least 1 comment")
        _show("response", body)


def s_url_x(base: str, key: str | None):
    """/url/ catch-all with an X status URL."""
    target = "https%3A%2F%2Fx.com%2FQwenDevs%2Fstatus%2F2084102417885585597"
    status, body = request(base, f"/url/{target}", key=key)
    _check(status == 200, f"expected 200, got {status}")
    if isinstance(body, dict):
        _check(body.get("status") in ("ok", "partial"),
               f"status should be ok/partial, got '{body.get('status')}'")
        item = body.get("item")
        _check(item is not None, "expected item from X URL")
        _show("response", body)


def s_url_web(base: str, key: str | None):
    """/url/ catch-all with an unknown host (example.com)."""
    target = "https%3A%2F%2Fexample.com"
    status, body = request(base, f"/url/{target}", key=key)
    _check(status == 200, f"expected 200, got {status}")
    if isinstance(body, dict):
        _check(body.get("status") in ("ok", "partial"),
               f"status should be ok/partial, got '{body.get('status')}'")
        item = body.get("item")
        if item:
            _check("Example Domain" in (item.get("title") or ""),
                   "expected 'Example Domain' title")
            _show("response", body)


def s_instances(base: str, key: str | None):
    """Instance list is populated."""
    status, body = request(base, "/instances", key=key)
    _check(status == 200, f"expected 200, got {status}")
    if isinstance(body, dict):
        instances = body.get("instances") or []
        _check(len(instances) > 0, "expected at least 1 instance")
        _check(instances[0] == "nitter.net", "nitter.net should be first")
        _show("response", body)


def s_archive(base: str, key: str | None):
    """Archive read (may be empty if nothing archived yet)."""
    status, body = request(base, "/archive/x/QwenDevs", key=key)
    # 200 = archived data exists; 404 = not archived yet; 503 = S3 not configured
    _check(status in (200, 404, 503), f"expected 200/404/503, got {status}")
    if status == 200:
        _show("response", body)
    elif status == 404:
        print("  not archived yet (run /x/QwenDevs first, then retry)")
    else:
        print("  S3 archive not configured (set CRAWLER_S3_ENDPOINT)")


def s_search_ddg(base: str, key: str | None):
    """Web search via DuckDuckGo (no SearXNG needed)."""
    status, body = request(
        base, "/search?q=python+asyncio&provider=duckduckgo&limit=3", key=key,
    )
    if isinstance(body, dict) and body.get("status") == "failed":
        print(f"  (DDG rate-limited or unavailable: {body.get('error', '')[:80]})")
        print("  skipping — not a failure, DDG may be rate-limited from datacenter IPs")
        return
    _check(status == 200, f"expected 200, got {status}")
    if isinstance(body, dict):
        _check(body.get("status") in ("ok", "partial"),
               f"status should be ok/partial, got '{body.get('status')}'")
        items = body.get("items") or []
        _check(len(items) > 0, "expected at least 1 search result")
        _check(items[0]["platform"] == "search", "platform should be search")
        _show("response", body)


def s_search_searxng(base: str, key: str | None):
    """Web search via SearXNG (self-hosted, 70+ engines)."""
    status, body = request(
        base, "/search?q=python+httpx&provider=searxng&limit=3", key=key,
    )
    if isinstance(body, dict) and body.get("status") == "failed":
        print(f"  (SearXNG not available: {body.get('error', '')[:80]})")
        print("  skipping — not a failure, SearXNG container may not be running")
        return
    _check(status == 200, f"expected 200, got {status}")
    if isinstance(body, dict):
        _check(body.get("status") in ("ok", "partial"),
               f"status should be ok/partial, got '{body.get('status')}'")
        items = body.get("items") or []
        _check(len(items) > 0, "expected at least 1 search result")
        _show("response", body)


def s_search_auto(base: str, key: str | None):
    """Web search with auto provider (SearXNG → DDG fallback)."""
    status, body = request(
        base, "/search?q=latest+AI+news&provider=auto&limit=5", key=key,
    )
    _check(status == 200, f"expected 200, got {status}")
    if isinstance(body, dict):
        _check(body.get("status") in ("ok", "partial"),
               f"status should be ok/partial, got '{body.get('status')}'")
        items = body.get("items") or []
        _check(len(items) > 0, "expected at least 1 search result")
        _check(body.get("source", "").startswith("search:"),
               f"source should start with 'search:', got '{body.get('source')}'")
        _show("response", body)


def s_search_news(base: str, key: str | None):
    """Search news category via SearXNG."""
    status, body = request(
        base, "/search?q=AI&provider=searxng&categories=news&limit=3", key=key,
    )
    if isinstance(body, dict) and body.get("status") == "failed":
        print(f"  (news search unavailable: {body.get('error', '')[:80]})")
        print("  skipping — not a failure")
        return
    _check(status == 200, f"expected 200, got {status}")
    if isinstance(body, dict):
        items = body.get("items") or []
        _check(len(items) > 0, "expected at least 1 news result")
        _show("response", body)


# ─── All scenarios ────────────────────────────────────────────

SCENARIOS = {
    "health": ("Health check", s_health),
    "auth-required": ("Auth enforcement", s_auth_required),
    "auth-page": ("Login page (/auth)", s_auth_page),
    "x-feed": ("X feed (Nitter RSS)", s_x_feed),
    "x-post": ("X single post (syndication)", s_x_post),
    "x-thread": ("X thread walk", s_x_thread),
    "x-replies": ("X replies (browser tier)", s_x_replies),
    "substack-native": ("Substack feed (native domain)", s_substack_feed_native),
    "substack-custom": ("Substack feed (custom domain)", s_substack_feed_custom),
    "substack-comments": ("Substack comments (API)", s_substack_comments),
    "url-x": ("URL catch-all (X status)", s_url_x),
    "url-web": ("URL catch-all (example.com)", s_url_web),
    "search-ddg": ("Search (DuckDuckGo)", s_search_ddg),
    "search-searxng": ("Search (SearXNG)", s_search_searxng),
    "search-auto": ("Search (auto fallback)", s_search_auto),
    "search-news": ("Search (news category)", s_search_news),
    "instances": ("Instance list", s_instances),
    "archive": ("Archive read", s_archive),
}


def main():
    parser = argparse.ArgumentParser(
        description="End-to-end smoke tests for the crawler service.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Scenarios:
  health             Health check + config snapshot
  auth-required      Verify auth is enforced (401 without key)
  auth-page          Browser login form at /auth
  x-feed             X user feed via Nitter RSS
  x-post             Single X post via syndication JSON
  x-thread           Reply chain walk via syndication
  x-replies          Replies to a tweet (browser tier)
  substack-native    Substack feed (platformer.substack.com)
  substack-custom    Substack feed (lennysnewsletter custom domain)
  substack-comments  Substack post comments via public API
  url-x              /url/ catch-all with an X URL
  url-web            /url/ catch-all with example.com
  search-ddg          Search via DuckDuckGo (no container)
  search-searxng      Search via SearXNG (70+ engines)
  search-auto         Search with auto provider fallback
  search-news         Search news category
  instances          Nitter instance discovery
  archive            S3 archive read

Examples:
  python3 tests/test_e2e.py
  python3 tests/test_e2e.py --base http://crawler.example.com:8321 --key sk-abc
  python3 tests/test_e2e.py --only health,x-feed,x-post
  python3 tests/test_e2e.py --skip x-replies,archive
""",
    )
    parser.add_argument(
        "--base", default=DEFAULT_BASE,
        help=f"Base URL of the crawler service (default: {DEFAULT_BASE})",
    )
    parser.add_argument("--key", default=None, help="API key for Bearer auth")
    parser.add_argument(
        "--only", default=None,
        help="Comma-separated scenario names to run (default: all)",
    )
    parser.add_argument(
        "--skip", default=None,
        help="Comma-separated scenario names to skip",
    )
    args = parser.parse_args()

    # Select scenarios
    selected = SCENARIOS
    if args.only:
        names = {n.strip() for n in args.only.split(",")}
        selected = {k: v for k, v in SCENARIOS.items() if k in names}
    if args.skip:
        names = {n.strip() for n in args.skip.split(",")}
        selected = {k: v for k, v in selected.items() if k not in names}

    if not selected:
        print("No scenarios selected.")
        sys.exit(1)

    print(f"\n{'#'*60}")
    print(f"  crawler e2e — {args.base}")
    print(f"  key: {'✓ set' if args.key else '✗ none (public mode or no auth)'}")
    print(f"  scenarios: {', '.join(selected.keys())}")
    print(f"{'#'*60}")

    for name, (label, fn) in selected.items():
        run(label, fn, args.base, args.key)

    # Summary
    total = _passed + _failed
    print(f"\n{'─'*60}")
    print(f"  {_passed} passed | {_failed} failed | {total} total")
    print(f"{'─'*60}")

    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
