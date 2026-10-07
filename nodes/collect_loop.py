"""Keeps the queue stocked: feeds on a timer, the tweet stream continuously.

Two speeds on purpose. Sites do not publish faster than POLL_MINUTES, but
tweets are where breaking news shows up first, so waiting ten minutes to notice
a WatcherGuru alert would waste the whole advantage of having the X feed.

This file never writes posts, calls a model, or sends anything — it only turns
"something exists out there" into "a row in our database".
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone

import config
from nodes import dedup, fetch_pages, fetch_rss, fetch_tweets
from utils import db, logger as log_setup, textclean

log = log_setup.get("collect")


def _is_stale(article: fetch_rss.Article) -> bool:
    """True if the article is older than we care about.

    Catches abandoned feeds that still respond perfectly with months-old
    articles, and a newly added feed handing over its whole back catalogue.
    An article with NO date counts as fresh — better slightly old than dropping
    real news because a feed omitted a date.
    """
    if article.published is None:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.ARTICLE_MAX_AGE_HOURS)
    return article.published < cutoff


def _store_article(article: fetch_rss.Article) -> bool:
    """Save a feed article if it is new. Runs the cheap filters on the way in."""
    if _is_stale(article):
        return False
    if article.baseline:
        # Remembered so it is never news later, but never queued.
        db.insert_item(origin="rss", source_name=article.source_name,
                       external_id=textclean.normalise_url(article.url), url=article.url,
                       title=article.title, topic_hint=article.topic, status="duplicate",
                       status_reason="already on the page when we started watching it")
        return False

    normalised_url = textclean.normalise_url(article.url)
    norm_title = textclean.normalise_headline(article.title)
    fingerprint = textclean.title_hash(article.title)

    item_id = db.insert_item(
        origin="rss",
        source_name=article.source_name,
        external_id=normalised_url,
        url=article.url,
        title=article.title,
        body=article.summary,
        published_at=(article.published.strftime("%Y-%m-%d %H:%M:%S")
                      if article.published else None),
        norm_title=norm_title,
        title_hash=fingerprint,
        topic_hint=article.topic,
        link_url=article.link_url,
    )

    # None means the link was already stored — the normal outcome.
    if item_id is None:
        return False

    # The same headline arriving from a different address.
    if dedup.check_headline(item_id, article.title, fingerprint):
        db.set_item_status(item_id, "duplicate", "same headline already seen")
        db.bump_counter("deduped_headline")
        return False

    db.bump_counter("ingested")
    return True


_X_HOSTS = ("x.com/", "twitter.com/", "t.co/", "pic.x.com/", "pic.twitter.com/")


def _readable(text: str, links: list[dict]) -> str:
    """The tweet's words with each t.co link replaced by its real address, the rest dropped."""
    for link in links:
        if link.get("short") and link.get("url"):
            text = text.replace(link["short"], textclean.strip_utm(link["url"]))
    return re.sub(r"https?://t\.co/\S+", "", text).strip()


def tweet_source(tweet: fetch_tweets.Tweet) -> tuple[str, str, list[dict]]:
    """(title, labelled source text, outside links to read) for one tweet.

    The tracked account's post comes first, then the post it quotes or reposts, each
    under a label, so the models can tell who said what. Links to X itself are left
    out: the shared post's text already arrives with the tweet.
    """
    handle = tweet.handle.lower()
    own = _readable(tweet.text, list(tweet.links))
    shared = tweet.shared or {}
    other = (shared.get("handle") or "unknown").lower()
    shared_text = _readable(shared.get("text") or "", shared.get("links") or [])

    if shared.get("kind") == "retweeted":
        title = textclean.tweet_to_title(shared_text)
        body = f"@{handle} REPOSTED this post by @{other} ({shared.get('url', '')}):\n{shared_text}"
    else:
        title = textclean.tweet_to_title(own)
        body = f"POST by @{handle} on X ({tweet.url}):\n{own}"
        if shared:
            body += f"\n\nQUOTED POST by @{other} ({shared.get('url', '')}):\n{shared_text}"

    links, seen = [], set()
    for link in [*tweet.links, *(shared.get("links") or [])]:
        url = textclean.strip_utm(link.get("url") or "")
        if not url.startswith("http") or any(host in url for host in _X_HOSTS) or url in seen:
            continue
        seen.add(url)
        links.append({"url": url, "title": link.get("title") or "",
                      "description": link.get("description") or ""})
    return title, body, links[:config.TWEET_MAX_LINKS]


def _store_tweet(tweet: fetch_tweets.Tweet) -> bool:
    """Save a tweet if it is new, as a labelled source with its links and all its media.

    Tweets have no headline, so the opening line becomes one — that is what
    lets a tweet be matched against an article about the same event.
    """
    title, body, links = tweet_source(tweet)
    norm_title = textclean.normalise_headline(title)
    fingerprint = textclean.title_hash(title)

    shared = tweet.shared or {}
    images = [*tweet.media, *(shared.get("media") or [])]
    videos = [{"url": v, "kind": k or "video"} for v, k in
              ((tweet.video, tweet.video_kind), (shared.get("video", ""), shared.get("video_kind", "")))
              if v]
    if tweet.handle in config.NO_MEDIA_SOURCES:
        images, videos = [], []

    item_id = db.insert_item(
        origin="x",
        source_name=tweet.handle,
        external_id=tweet.tweet_id,
        url=tweet.url,
        title=title,
        body=body,
        image_url=images[0] if images else "",
        video_url=videos[0]["url"] if videos else "",
        video_kind=videos[0]["kind"] if videos else "",
        published_at=None,   # X's own timestamp format differs; fetched_at is enough
        norm_title=norm_title,
        title_hash=fingerprint,
        topic_hint=config.X_ACCOUNTS.get(tweet.handle, ""),
        # The page the post is about is the link readers want, not the tweet.
        link_url=links[0]["url"] if links else "",
        links_json=json.dumps(links) if links else "",
    )

    if item_id is None:
        return False
    if images or videos:
        # Every picture and clip, the shared post's too; the analysts choose.
        db.add_item_media(item_id, images=images, videos=videos)

    if dedup.check_headline(item_id, title, fingerprint):
        db.set_item_status(item_id, "duplicate", "same headline already seen")
        db.bump_counter("deduped_headline")
        return False

    db.bump_counter("ingested")
    return True


async def collect_feeds_once() -> int:
    """Read every feed once and store what's new. Returns how many were new."""
    articles = await fetch_rss.execute() + await fetch_pages.execute()
    stale = sum(1 for article in articles if _is_stale(article))
    new_count = sum(1 for article in articles if _store_article(article))

    if stale:
        log.info("Feeds: %d offered, %d new, %d too old (over %dh)",
                 len(articles), new_count, stale, config.ARTICLE_MAX_AGE_HOURS)
    else:
        log.info("Feeds: %d article(s) offered, %d new", len(articles), new_count)
    return new_count


def reads_tweets() -> bool:
    """A channel that follows no X accounts stays off the shared tweet stream."""
    return bool(config.X_ACCOUNTS)


async def collect_tweets_once() -> int:
    """Take whatever tweets are waiting and store them. Returns how many were new."""
    if not reads_tweets():
        return 0
    tweets = await fetch_tweets.drain_once()
    new_count = sum(1 for tweet in tweets if _store_tweet(tweet))

    if tweets:
        log.info("Tweets: %d offered, %d new", len(tweets), new_count)
    return new_count


async def _feed_task() -> None:
    """Poll the feeds every POLL_MINUTES, forever."""
    while True:
        try:
            await collect_feeds_once()
        except Exception as error:  # noqa: BLE001 - one bad cycle must not end the loop
            log.exception("Feed cycle failed: %s", error)
            from utils import telegram_error
            telegram_error.send_error(str(error), node_name="collect_feeds")

        await asyncio.sleep(config.POLL_MINUTES * 60)


async def _tweet_task() -> None:
    """Watch the tweet stream continuously and store what arrives."""
    async for batch in fetch_tweets.stream():
        try:
            new_count = sum(1 for tweet in batch if _store_tweet(tweet))
            log.info("Tweets: %d arrived, %d new", len(batch), new_count)
        except Exception as error:  # noqa: BLE001
            log.exception("Could not store a batch of tweets: %s", error)
            from utils import telegram_error
            telegram_error.send_error(str(error), node_name="collect_tweets")


async def run(once: bool = False) -> None:
    """Run collection. `once` does a single pass over both sources and stops."""
    if once:
        log.info("Single collection pass...")
        feeds = await collect_feeds_once()
        tweets = await collect_tweets_once()
        log.info("Done: %d new from feeds, %d new from X", feeds, tweets)
        return

    log.info("Collecting: feeds every %d min, tweets continuously",
             config.POLL_MINUTES)
    await asyncio.gather(_feed_task(), *([_tweet_task()] if reads_tweets() else []))
