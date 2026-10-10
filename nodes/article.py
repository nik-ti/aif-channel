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
import json
import re
from datetime import datetime, timedelta, timezone

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


# Where a page states its own publish date: meta tags, then schema.org JSON.
_META = re.compile(r"<meta\s[^>]*>", re.IGNORECASE)
_ATTR = re.compile(r'([\w:-]+)\s*=\s*["\']([^"\']*)["\']')
_DATE_NAMES = {"article:published_time", "og:published_time", "datepublished", "pubdate", "publish-date"}
_JSON_DATE = re.compile(r'datePublished\\*"\s*:\s*\\*"(\d{4}-\d{2}-\d{2}[^"\\]*)')


class StalePage(Exception):
    """A feed article whose own page says it is older than ARTICLE_MAX_AGE_HOURS."""


def page_date(html: str) -> datetime | None:
    """The publish date the page states about itself, or None if it states none."""
    from nodes.fetch_rss import _parse_date
    for tag in _META.findall(html or ""):
        attrs = {key.lower(): value for key, value in _ATTR.findall(tag)}
        name = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
        if name in _DATE_NAMES and (found := _parse_date(attrs.get("content", ""))):
            return found
    match = _JSON_DATE.search(html or "")
    return _parse_date(match.group(1)) if match else None


def is_old(date: datetime | None, max_age_hours: float) -> bool:
    """True if a page date is past the limit. A day of slack, since many pages give only the day."""
    if date is None:
        return False
    return date < datetime.now(timezone.utc) - timedelta(hours=max_age_hours + 24)


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


async def _plain(url: str) -> tuple[str | None, str]:
    """Fetch and extract without a browser. The common path. Returns (text, page html)."""
    try:
        async with httpx.AsyncClient(
            timeout=config.ARTICLE_TIMEOUT_SECONDS, follow_redirects=True,
            headers={"User-Agent": _UA},
        ) as client:
            response = await client.get(url)
        if response.status_code != 200:
            log.debug("Plain fetch got HTTP %s for %s", response.status_code, url[:80])
            return None, ""
    except Exception as error:  # noqa: BLE001 - a slow site must not stop the channel
        log.debug("Plain fetch failed for %s: %s", url[:80], error)
        return None, ""

    # include_comments=False keeps reader comments out of what the writer is
    # told is the source; they read like reporting and are not.
    text = trafilatura.extract(response.text, include_comments=False,
                               include_tables=False, favor_precision=True)
    return (text if _usable(text) else None), response.text


async def _browser(url: str) -> tuple[str | None, str]:
    """Fetch through crawl4ai's stealth browser, for sites that refuse step 1. (text, html)"""
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    except ImportError:
        log.warning("crawl4ai is not installed; skipping the browser path")
        return None, ""

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
            return None, ""

    html = getattr(result, "html", "") or ""
    text = trafilatura.extract(html, include_comments=False, include_tables=False,
                               favor_precision=True) if html else None
    if not _usable(text):
        # crawl4ai's own markdown, in case trafilatura disliked the shape.
        markdown = getattr(result, "markdown", None)
        text = str(markdown) if markdown else None
    return (text if _usable(text) else None), html


async def _reader(url: str) -> str | None:
    """The article through a reader service, for pages behind a JavaScript challenge."""
    if not config.READER_FALLBACK_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=config.ARTICLE_TIMEOUT_SECONDS * 3,
                                     follow_redirects=True) as client:
            response = await client.get(config.READER_FALLBACK_URL + url)
        if response.status_code != 200:
            return None
    except Exception as error:  # noqa: BLE001
        log.debug("Reader service failed for %s: %s", url[:80], error)
        return None
    text = response.text
    # Its reply opens with Title / URL Source lines; the article follows this marker.
    _, marker, body = text.partition("Markdown Content:")
    text = (body if marker else text).strip()
    return text if _usable(text) else None


async def _reader_html(url: str) -> str:
    """The page's HTML through the reader service, for its pictures and players."""
    try:
        async with httpx.AsyncClient(timeout=config.ARTICLE_TIMEOUT_SECONDS * 3,
                                     follow_redirects=True,
                                     headers={"X-Return-Format": "html"}) as client:
            response = await client.get(config.READER_FALLBACK_URL + url)
        return response.text if response.status_code == 200 else ""
    except Exception as error:  # noqa: BLE001
        log.debug("Reader service gave no HTML for %s: %s", url[:80], error)
        return ""


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


# An article ABOUT the thing (a blog post, a news page) rather than the thing itself. A dated
# path (/2026/10/08/) is how news sites like TechCrunch and 9to5Google file their stories.
_ARTICLE_PATH = re.compile(r"/(blog|news|index|research|announcements?|posts?|press)/|/20\d\d/\d\d/",
                           re.IGNORECASE)
# Where a released thing itself lives when the maker has no product page: its code or model.
_CODE_HOSTS = ("github.com", "huggingface.co")
TRY_HOSTS = ("experience.", "demo.", "try.", "play.", "playground.", "app.", "studio.", "chat.")


def site_of(url: str) -> str:
    """The last two parts of the host: cloudflare.com for blog.cloudflare.com."""
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower().split(":")[0]
    return ".".join(host.split(".")[-2:])


def is_article_url(url: str) -> bool:
    """True for a blog post or news page (blog.x.com, /blog/, /news/...), not a product."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return parsed.netloc.lower().startswith(("blog.", "news.")) or bool(_ARTICLE_PATH.search(parsed.path))


def product_link(html: str, page_url: str) -> str:
    """Where to use the thing an aggregator page is about, or "" if it only links articles.

    Only for sites named in PRODUCT_LINK_PAGES; anywhere else the page IS the source.
    Picks, in order: a "try it" site, the maker's own page that is not an article (Cloudflare's
    model page, not its blog post about it), the thing's code or model on GitHub or Hugging Face.
    Never a news site, someone's blog or a video about it.
    An announcement is never the link: the post already says what it says (nikita, 2026-10-10).
    """
    from urllib.parse import urlparse
    from bs4 import BeautifulSoup

    host = urlparse(page_url).netloc.lower()
    if not any(host == site or host.endswith("." + site) for site in config.PRODUCT_LINK_PAGES):
        return ""
    soup = BeautifulSoup(html or "", "lxml")
    body = soup.find("main") or soup.find("article") or soup.body or soup
    links = []
    for tag in body.find_all("a", href=True):
        href = tag["href"].strip()
        target = urlparse(href).netloc.lower()
        if (href.startswith("http") and target and target != host
                and not target.endswith("." + host) and href not in links):
            links.append(href)
    makers = {site_of(link) for link in links if is_article_url(link)}
    usable = [link for link in links if not is_article_url(link)]
    for choice in ([u for u in usable if urlparse(u).netloc.lower().startswith(TRY_HOSTS)],
                   [u for u in usable if site_of(u) in makers],
                   [u for u in usable if site_of(u) in _CODE_HOSTS]):
        if choice:
            return choice[0]
    return ""


async def _read(url: str) -> tuple[str | None, str, str]:
    """(text, html, how) for one page: a plain request, then the browser, then the reader."""
    text, html = await _plain(url)
    used = "plain"
    if text is None:
        text, html = await _browser(url)
        used = "browser"
    if text is None:
        text = await _reader(url)
        used = "reader"
        if text and config.COLLECT_ARTICLE_MEDIA:
            html = await _reader_html(url)
    return text, html or "", used


async def _tweet_pages(item) -> str | None:
    """A tweet's source with the pages it links to read in, each under its own label.

    The tweet is the trigger; the linked announcement, docs or repo carry the detail.
    A page that cannot be read is represented by X's own preview of it, if any.
    """
    try:
        links = json.loads(item["links_json"] or "[]") if "links_json" in item.keys() else []
    except json.JSONDecodeError:
        links = []
    if not links:
        return None
    budget = config.ARTICLE_MAX_CHARS // len(links)
    parts, read = [(item["body"] or "").strip()], 0
    for number, link in enumerate(links, start=1):
        url = link["url"]
        text, html, used = await _read(url)
        if config.COLLECT_ARTICLE_MEDIA and html:
            from nodes import media
            images, videos = media.from_article_html(html, url)
            if images or videos:
                db.add_item_media(item["id"], images=images, videos=videos)
        preview = "\n".join(p for p in (link.get("title"), link.get("description")) if p)
        dated = page_date(html)
        label = f"{url} (page dated {dated:%Y-%m-%d})" if dated else url
        if text:
            read += 1
            content = text.strip()[:budget]
            log.info("Tweet %s: linked page %d read via %s (%d chars)", item["id"], number, used, len(content))
        else:
            content = preview or "(the page could not be read)"
        parts.append(f"LINKED PAGE {number}: {label}\n{content}")
    (_record_success if read else _record_failure)()
    combined = "\n\n".join(parts)
    db.set_article_text(item["id"], combined)
    return combined


async def fetch_for(item) -> str | None:
    """The article behind this item, cached on the row. None if there is none.
    Raises StalePage when a feed article's own page is too old to be news.

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
    # A tweet's own link is the tweet itself, and x.com answers a logged-out reader
    # with its sign-in page (39 of the first 58 fetches stored that page as "the
    # article"). What a tweet links OUT to is read instead.
    if any(host in url for host in ("x.com/", "twitter.com/")):
        return await _tweet_pages(item)

    text, html, used = await _read(url)
    # Aggregators like Future Tools date an item when THEY list it, so the
    # page's own date is the one to trust (an old launch can be relisted).
    dated = page_date(html)
    if item["origin"] == "rss" and is_old(dated, config.ARTICLE_MAX_AGE_HOURS):
        db.set_item_status(item_id, "skipped_stale", f"the article page is dated {dated:%Y-%m-%d}")
        log.info("Item %s skipped: its page is dated %s (%s)", item_id, f"{dated:%Y-%m-%d}", url[:70])
        raise StalePage(url)
    known = (item["link_url"] if "link_url" in item.keys() else "") or ""
    if config.PRODUCT_LINK_PAGES and html and not known:
        link = product_link(html, url)
        if link:
            db.set_item_link(item_id, link)
            log.info("Product link for item %s: %s", item_id, link[:80])
    if config.COLLECT_ARTICLE_MEDIA and html:
        from nodes import media
        images, videos = media.from_article_html(html, url)
        if images or videos:
            db.add_item_media(item_id, images=images, videos=videos)
            log.info("Article media for item %s: %d image(s), %d video(s)",
                     item_id, len(images), len(videos))

    if text is None:
        _record_failure()
        log.info("No article for item %s (%s)", item_id, url[:70])
        return None

    _record_success()
    text = text.strip()[:config.ARTICLE_MAX_CHARS]
    db.set_article_text(item_id, text)
    log.info("Article read for item %s via %s: %d chars", item_id, used, len(text))
    return text
