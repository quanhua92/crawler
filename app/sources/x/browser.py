"""Browser-tier X sources — fetch replies and extended timelines via GraphQL intercept.

When Tier-1 (Nitter RSS / syndication) can't provide data (replies to a tweet,
>20 posts from a feed), the browser navigates to x.com, lets Twitter's JS fire
its GraphQL requests, and intercepts the JSON responses containing tweet data.

Requires CRAWLER_BROWSER_ENABLED=true and a warm browser pool.
"""

from __future__ import annotations

import logging

from app.models import Author, Media, Post

logger = logging.getLogger("crawler.x.browser")


async def fetch_replies(tweet_id: str, *, limit: int = 50) -> list[Post]:
    """Navigate to a tweet page, intercept GraphQL, extract reply tweets.

    Returns all tweets in the conversation thread (excluding the root tweet).
    """
    tweets = await _capture_graphql(
        f"https://x.com/i/status/{tweet_id}",
        graphql_keywords=("TweetDetail", "ConversationTimeline", "tweet-result"),
    )

    # Deduplicate by id, exclude the root tweet itself
    seen: dict[str, dict] = {}
    for t in tweets:
        tid = t.get("rest_id") or t.get("id_str")
        if tid and tid != tweet_id:
            seen.setdefault(tid, t)

    posts = [_graphql_to_post(t, "browser") for t in seen.values()]
    return posts[:limit]


async def fetch_timeline(handle: str, *, limit: int = 50) -> list[Post]:
    """Navigate to a user profile, intercept GraphQL UserTweets, extract posts.

    Works for limits >20 (beyond Nitter RSS range). Scrolls if needed.
    """
    tweets = await _capture_graphql(
        f"https://x.com/{handle.lstrip('@')}",
        graphql_keywords=("UserTweets", "UserTweetsAndReplies", "timeline"),
        scroll_for_more=limit > 20,
        max_scrolls=(limit // 20) + 1,
    )

    seen: dict[str, dict] = {}
    for t in tweets:
        tid = t.get("rest_id") or t.get("id_str")
        if tid:
            seen.setdefault(tid, t)

    posts = [_graphql_to_post(t, "browser") for t in seen.values()]
    return posts[:limit]


async def _capture_graphql(
    url: str,
    *,
    graphql_keywords: tuple[str, ...],
    scroll_for_more: bool = False,
    max_scrolls: int = 0,
) -> list[dict]:
    """Navigate to url, intercept GraphQL XHR responses, extract raw tweet dicts."""
    from app.browser import _acquire, _release

    captured: list[dict] = []
    tweet_dicts: list[dict] = []

    ctx = await _acquire()
    try:
        page = await ctx.new_page()

        def on_response(response):
            resp_url = response.url
            if not any(kw in resp_url for kw in graphql_keywords):
                return
            try:
                data = response.json()
                captured.append(data)
            except Exception:
                pass

        page.on("response", on_response)

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        if scroll_for_more:
            for _ in range(max_scrolls):
                prev_count = len(tweet_dicts)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)
                _parse_captured(captured, tweet_dicts)
                if len(tweet_dicts) == prev_count:
                    break  # no new tweets loaded

        _parse_captured(captured, tweet_dicts)
        await page.close()
    except Exception as e:
        logger.warning("browser GraphQL capture failed: %s: %s", type(e).__name__, e)
    finally:
        await _release(ctx)

    return tweet_dicts


def _parse_captured(captured: list[dict], tweet_dicts: list[dict]) -> None:
    """Walk captured GraphQL JSON trees, extract tweet-like objects."""
    for data in captured:
        _walk_for_tweets(data, tweet_dicts)


def _walk_for_tweets(obj, out: list[dict]) -> None:
    """Recursively walk a JSON tree, collecting objects that look like tweets."""
    if isinstance(obj, dict):
        # Twitter internal format: tweet objects have rest_id + legacy
        # Syndication format: id_str + text
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
    """Convert a raw Twitter GraphQL tweet object to a Post.

    Handles both internal format (rest_id + legacy) and syndication format (id_str + text).
    """
    legacy = raw.get("legacy") or raw
    tid = raw.get("rest_id") or raw.get("id_str") or legacy.get("id_str", "")

    user = raw.get("core", {}).get("user_results", {}).get("result", {}) if raw.get("core") else {}
    user_legacy = user.get("legacy", user)
    screen_name = user_legacy.get("screen_name") or raw.get("user", {}).get("screen_name", "")
    user_name = user_legacy.get("name") or raw.get("user", {}).get("name")

    text = legacy.get("full_text") or legacy.get("text") or raw.get("text", "")

    media: list[Media] = []
    for m in (legacy.get("extended_entities") or {}).get("media", []):
        media.append(Media(
            type=m.get("type", "photo"),
            url=m.get("media_url_https", ""),
            expanded_url=m.get("expanded_url"),
        ))

    metrics: dict[str, int] = {}
    for k in ("favorite_count", "retweet_count", "reply_count", "quote_count", "view_count"):
        val = legacy.get(k) or raw.get(k)
        if val is not None:
            metrics[k] = int(val)

    return Post(
        id=str(tid),
        platform="x",
        url=f"https://x.com/{screen_name}/status/{tid}" if screen_name else "",
        author=Author(
            id=user_legacy.get("id_str") or raw.get("user", {}).get("id_str"),
            username=screen_name,
            name=user_name,
        ),
        text=text,
        lang=legacy.get("lang") or raw.get("lang"),
        metrics=metrics,
        media=media,
        reply_to=legacy.get("in_reply_to_status_id_str"),
        source=source,
    )
