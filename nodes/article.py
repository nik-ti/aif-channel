"""Reads the article behind a link, because the writer needs more than a headline —
59% of items arrive with a body under 120 characters.

There are two ways in: a plain request with trafilatura, which takes about a
second and works for 7 of 8 sources, and crawl4ai in stealth mode for the ones
that answer 403, such as The Block. Only one crawl runs at a time and the browser
is closed on exit.

It fails open: no article means the item keeps its headline.
"""

from __future__ import annotations

import asyncio

import httpx
import trafilatura

import config
from utils import db, logger as log_setup

log = log_setup.get("article")

# A browser's, because some servers vary the response by user agent alone and
# a default python-httpx string is the fastest way to be served a stub.
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# Below this the extraction did not find an article: a consent wall, a bot
# check, or a page whose text lives in JavaScript. Shorter than the shortest
# real story these feeds publish, so a terse-but-real article still counts.
_MIN_CHARS = 400

# Only one crawl at a time, process-wide. The publish loop is already
# sequential, but a sweep or a future parallel round must not be able to open
# a second browser — that is the failure mode being designed out.
_browser_lock = asyncio.Lock()

_consecutive_failures = 0
FAILURE_ALERT_AFTER = 20


# What a bot check, a consent wall or a dead page says. Length alone is not a
# test: The Block's "Performing security verification" page is 510 characters
# and would otherwise have been stored and handed to the writer as the article.
_NOT_AN_ARTICLE = (
    "security verification", "checking your browser", "enable javascript",
    "captcha", "are you a robot", "ddos protection", "access denied",
    "unusual traffic", "verify you are human", "cookies to continue",
    "subscribe to continue", "page not found",
)


def _usable(text: str | None) -> bool:
    """True if this looks like an article rather than a wall, a stub or a check."""
    if not text:
        return False
    stripped = text.strip()
    if len(stripped) < _MIN_CHARS:
        return False
    # Only the opening matters: a real article about CAPTCHAs is still an
    # article, but a bot check announces itself in its first lines.
    head = stripped[:600].lower()
    return not any(marker in head for marker in _NOT_AN_ARTICLE)


async def _plain(url: str) -> str | None:
    """Fetch and extract without a browser. The common path."""
    try:
        async with httpx.AsyncClient(
            timeout=config.ARTICLE_TIMEOUT_SECONDS, follow_redirects=True,
            headers={"User-Agent": _UA},
        ) as client:
            response = await client.get(url)
        if response.status_code != 200:
            log.debug("Plain fetch got HTTP %s for %s", response.status_code, url[:80])
            return None
    except Exception as error:  # noqa: BLE001 - a slow site must not stop the channel
        log.debug("Plain fetch failed for %s: %s", url[:80], error)
        return None

    # include_comments=False keeps reader comments out of what the writer is
    # told is the source; they read like reporting and are not.
    text = trafilatura.extract(response.text, include_comments=False,
                               include_tables=False, favor_precision=True)
    return text if _usable(text) else None


async def _browser(url: str) -> str | None:
    """Fetch through crawl4ai's stealth browser. Only for sites that refuse step 1."""
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    except ImportError:
        log.warning("crawl4ai is not installed; skipping the browser path")
        return None

    async with _browser_lock:
        try:
            # enable_stealth is what 0.9.x calls it; text_mode and light_mode
            # drop images and other chrome we never read, which is most of what
            # a browser would otherwise spend memory on.
            browser = BrowserConfig(headless=True, enable_stealth=True,
                                    text_mode=True, light_mode=True)
            async with AsyncWebCrawler(config=browser) as crawler:
                result = await asyncio.wait_for(
                    crawler.arun(url=url, config=CrawlerRunConfig(
                        page_timeout=config.ARTICLE_TIMEOUT_SECONDS * 1000,
                        simulate_user=True)),
                    timeout=config.ARTICLE_BROWSER_TIMEOUT_SECONDS,
                )
        except Exception as error:  # noqa: BLE001
            log.info("Browser fetch failed for %s: %s", url[:80], error)
            return None

    html = getattr(result, "html", "") or ""
    text = trafilatura.extract(html, include_comments=False, include_tables=False,
                               favor_precision=True) if html else None
    if not _usable(text):
        # crawl4ai's own markdown, in case trafilatura disliked the shape.
        markdown = getattr(result, "markdown", None)
        text = str(markdown) if markdown else None
    return text if _usable(text) else None


def _record_failure() -> None:
    global _consecutive_failures
    _consecutive_failures += 1
    if _consecutive_failures == FAILURE_ALERT_AFTER:
        from utils import telegram_error
        telegram_error.send_error(
            f"Article fetching has failed {_consecutive_failures} times in a row. "
            f"Posts are still going out, written from headlines alone, so nothing "
            f"looks broken — they are just thinner than they should be.",
            node_name="article",
        )


def _record_success() -> None:
    global _consecutive_failures
    _consecutive_failures = 0


async def fetch_for(item) -> str | None:
    """The article behind this item, cached on the row. None if there is none.

    Called once per item, after the sorter has kept it — there is no point
    paying for the ~85% that never get past that.
    """
    item_id = item["id"]
    url = (item["url"] or "").strip()

    cached = item["article_text"] if "article_text" in item.keys() else ""
    if cached:
        return cached
    if not url or not url.startswith("http"):
        return None
    # A tweet's link is the tweet itself, and x.com answers a logged-out reader
    # with its sign-in page. 39 of the first 58 fetches from X stored that page
    # as "the article" and handed it to the writer and the editor, which is how
    # a clean post about oil got rejected for containing X formatting it never
    # had. The tweet text is already the whole source.
    if any(host in url for host in ("x.com/", "twitter.com/")):
        return None

    text = await _plain(url)
    used = "plain"
    if text is None:
        text = await _browser(url)
        used = "browser"

    if text is None:
        _record_failure()
        log.info("No article for item %s (%s)", item_id, url[:70])
        return None

    _record_success()
    text = text.strip()[:config.ARTICLE_MAX_CHARS]
    db.set_article_text(item_id, text)
    log.info("Article read for item %s via %s: %d chars", item_id, used, len(text))
    return text
