"""Browser-tier X sources — rotate Nitter/xcancel instances first, x.com last.

When Tier-1 (Nitter RSS / syndication) can't provide data (replies to a tweet,
>20 posts from a feed), the browser loads the page on a Nitter instance and
parses the rendered HTML. The browser solves Cloudflare/antibot challenges
natively, so instances that block plain HTTP become usable.

Rotation order: xcancel.com (best health) → healthy Nitter instances → x.com
GraphQL intercept (last resort, your IP hits Twitter directly).

Requires CRAWLER_BROWSER_ENABLED=true and a warm browser pool.
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.models import Author, Media, Post

logger = logging.getLogger("crawler.x.browser")

# xcancel.com first — best health (97%) + browser solves its WASM antibot
_BROWSER_HOSTS = ["xcancel.com"]


async def _get_hosts() -> list[str]:
    """xcancel first, then healthy Nitter instances from the cache."""
    hosts = list(_BROWSER_HOSTS)
    try:
        from app.instances import get_instances

        for h in await get_instances():
            if h not in hosts:
                hosts.append(h)
    except Exception:
        pass
    return hosts


# ─── Public API ─────────────────────────────────────────────────


async def fetch_replies(tweet_id: str, *, limit: int = 50) -> list[Post]:
    """Fetch replies to a tweet — rotate Nitter instances, x.com fallback."""
    for host in await _get_hosts():
        posts = await _nitter_status_page(host, tweet_id, limit)
        if posts:
            logger.info("replies from nitter-browser:%s (%d items)", host, len(posts))
            return posts

    # Last resort: x.com GraphQL intercept
    posts = await _xcom_graphql_replies(tweet_id, limit)
    if posts:
        logger.info("replies from x.com GraphQL (%d items)", len(posts))
    return posts


async def fetch_timeline(handle: str, *, limit: int = 50) -> list[Post]:
    """Fetch >20 posts — rotate Nitter profile pages, x.com fallback."""
    handle = handle.lstrip("@")

    for host in await _get_hosts():
        posts = await _nitter_timeline_page(host, handle, limit)
        if posts:
            logger.info("timeline from nitter-browser:%s (%d items)", host, len(posts))
            return posts

    # Last resort: x.com GraphQL intercept
    posts = await _xcom_graphql_timeline(handle, limit)
    if posts:
        logger.info("timeline from x.com GraphQL (%d items)", len(posts))
    return posts


# ─── Nitter HTML parsing (primary path) ─────────────────────────


async def _nitter_status_page(host: str, tweet_id: str, limit: int) -> list[Post]:
    """Load a tweet page on a Nitter instance, parse replies from rendered HTML."""
    from app.browser import _acquire, _release

    ctx = await _acquire()
    try:
        page = await ctx.new_page()
        url = f"https://{host}/i/status/{tweet_id}"
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        items = await page.query_selector_all(".timeline-item")
        posts: list[Post] = []
        for item in items:
            post = await _parse_nitter_dom_item(item, host)
            if post and post.id != str(tweet_id):
                posts.append(post)

        await page.close()
        return posts[:limit]
    except Exception as e:
        logger.debug("nitter %s status page failed: %s", host, e)
        return []
    finally:
        await _release(ctx)


async def _nitter_timeline_page(host: str, handle: str, limit: int) -> list[Post]:
    """Load a profile page, scroll for more, parse posts from rendered HTML."""
    from app.browser import _acquire, _release

    ctx = await _acquire()
    try:
        page = await ctx.new_page()
        url = f"https://{host}/{handle}"
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # Scroll for more if we need >20
        max_scrolls = max(0, (limit // 20))
        seen_ids: set[str] = set()
        posts: list[Post] = []

        for _ in range(max_scrolls + 1):
            items = await page.query_selector_all(".timeline-item")
            for item in items:
                post = await _parse_nitter_dom_item(item, host)
                if post and post.id not in seen_ids:
                    seen_ids.add(post.id)
                    posts.append(post)
            if len(posts) >= limit or max_scrolls == 0:
                break
            await page.evaluate(
                "window.scrollTo(0, document.body.scrollHeight)"
            )
            await page.wait_for_timeout(2000)

        await page.close()
        return posts[:limit]
    except Exception as e:
        logger.debug("nitter %s timeline page failed: %s", host, e)
        return []
    finally:
        await _release(ctx)


async def _parse_nitter_dom_item(item, host: str) -> Post | None:
    """Parse a .timeline-item DOM element into a Post via browser selectors."""
    try:
        # Tweet ID from .tweet-link href
        link_el = await item.query_selector(".tweet-link")
        if not link_el:
            return None
        href = await link_el.get_attribute("href") or ""
        tid = href.split("/status/")[-1].split("#")[0].split("?")[0]
        if not tid.isdigit():
            return None

        # Text content
        content_el = await item.query_selector(".tweet-content")
        text = (await content_el.inner_text()) if content_el else ""

        # Author
        fullname_el = await item.query_selector(".fullname")
        username_el = await item.query_selector(".username")
        name = ((await fullname_el.inner_text()) if fullname_el else "").strip()
        username = (
            ((await username_el.inner_text()) if username_el else "").lstrip("@").strip()
        )

        # Timestamp (Nitter <time title="..."> has ISO datetime)
        created_at = None
        date_el = await item.query_selector(".tweet-date time")
        if date_el:
            iso = await date_el.get_attribute("title")
            if iso:
                try:
                    created_at = datetime.fromisoformat(
                        iso.replace("Z", "+00:00")
                    )
                except Exception:
                    pass

        # Media
        media: list[Media] = []
        for img in await item.query_selector_all("img"):
            src = await img.get_attribute("src") or ""
            if "twimg.com" in src and "profile_images" not in src:
                media.append(Media(type="photo", url=src))

        return Post(
            id=tid,
            platform="x",
            url=f"https://{host}{href}",
            author=Author(username=username, name=name) if username else None,
            text=text.strip(),
            created_at=created_at,
            media=media,
            source=f"nitter-browser:{host}",
        )
    except Exception as e:
        logger.debug("DOM parse failed: %s", e)
        return None


# ─── x.com GraphQL intercept (last resort) ──────────────────────


async def _xcom_graphql_replies(tweet_id: str, limit: int) -> list[Post]:
    """Navigate to x.com tweet page, intercept TweetDetail GraphQL."""
    tweets = await _capture_graphql(
        f"https://x.com/i/status/{tweet_id}",
        keywords=("TweetDetail", "ConversationTimeline", "tweet-result"),
    )
    seen: dict[str, dict] = {}
    for t in tweets:
        tid = t.get("rest_id") or t.get("id_str")
        if tid and tid != str(tweet_id):
            seen.setdefault(tid, t)
    return [_graphql_to_post(t, "xcom-browser") for t in seen.values()][:limit]


async def _xcom_graphql_timeline(handle: str, limit: int) -> list[Post]:
    """Navigate to x.com profile, intercept UserTweets GraphQL, scroll."""
    tweets = await _capture_graphql(
        f"https://x.com/{handle}",
        keywords=("UserTweets", "UserTweetsAndReplies", "timeline"),
        scroll_for_more=limit > 20,
        max_scrolls=(limit // 20) + 1,
    )
    seen: dict[str, dict] = {}
    for t in tweets:
        tid = t.get("rest_id") or t.get("id_str")
        if tid:
            seen.setdefault(tid, t)
    return [_graphql_to_post(t, "xcom-browser") for t in seen.values()][:limit]


async def _capture_graphql(
    url: str,
    *,
    keywords: tuple[str, ...],
    scroll_for_more: bool = False,
    max_scrolls: int = 0,
) -> list[dict]:
    """Navigate to url, intercept GraphQL XHR, extract raw tweet dicts."""
    from app.browser import _acquire, _release

    captured: list[dict] = []
    tweet_dicts: list[dict] = []

    ctx = await _acquire()
    try:
        page = await ctx.new_page()

        def on_response(response):
            if not any(kw in response.url for kw in keywords):
                return
            try:
                captured.append(response.json())
            except Exception:
                pass

        page.on("response", on_response)
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        if scroll_for_more:
            for _ in range(max_scrolls):
                prev = len(tweet_dicts)
                await page.evaluate(
                    "window.scrollTo(0, document.body.scrollHeight)"
                )
                await page.wait_for_timeout(2000)
                _parse_captured(captured, tweet_dicts)
                if len(tweet_dicts) == prev:
                    break

        _parse_captured(captured, tweet_dicts)
        await page.close()
    except Exception as e:
        logger.debug("x.com GraphQL capture failed: %s", e)
    finally:
        await _release(ctx)

    return tweet_dicts


def _parse_captured(captured: list[dict], out: list[dict]) -> None:
    for data in captured:
        _walk_for_tweets(data, out)


def _walk_for_tweets(obj, out: list[dict]) -> None:
    if isinstance(obj, dict):
        if obj.get("rest_id") and isinstance(obj.get("legacy"), dict):
            out.append(obj)
        elif obj.get("id_str") and ("text" in obj or "legacy" in obj):
            out.append(obj)
        for v in obj.values():
            _walk_for_tweets(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _walk_for_tweets(item, out)


def _graphql_to_post(raw: dict, source: str) -> Post:
    legacy = raw.get("legacy") or raw
    tid = raw.get("rest_id") or raw.get("id_str") or legacy.get("id_str", "")

    user = (
        raw.get("core", {}).get("user_results", {}).get("result", {})
        if raw.get("core")
        else {}
    )
    user_legacy = user.get("legacy", user)
    screen_name = (
        user_legacy.get("screen_name") or raw.get("user", {}).get("screen_name", "")
    )

    media: list[Media] = []
    for m in (legacy.get("extended_entities") or {}).get("media", []):
        media.append(Media(
            type=m.get("type", "photo"),
            url=m.get("media_url_https", ""),
        ))

    metrics: dict[str, int] = {}
    for k in ("favorite_count", "retweet_count", "reply_count", "quote_count"):
        val = legacy.get(k) or raw.get(k)
        if val is not None:
            metrics[k] = int(val)

    return Post(
        id=str(tid),
        platform="x",
        url=f"https://x.com/{screen_name}/status/{tid}" if screen_name else "",
        author=Author(
            username=screen_name,
            name=user_legacy.get("name"),
        ),
        text=legacy.get("full_text") or legacy.get("text") or raw.get("text", ""),
        lang=legacy.get("lang") or raw.get("lang"),
        metrics=metrics,
        media=media,
        reply_to=legacy.get("in_reply_to_status_id_str"),
        source=source,
    )
