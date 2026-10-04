"""Watches news pages that have no feed, such as x.ai/news, and returns the stories
that appeared since the last look.

Each page is read with a plain request first; if that fails or finds no story links
(a bot check, a page built by JavaScript), the stealth browser from nodes/article.py
reads it instead. The first look at a page only records what is already there.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlsplit

import config
from nodes import article
from nodes.fetch_rss import Article
from utils import db, logger as log_setup, textclean

log = log_setup.get("pages")

# Browsers are heavy and these pages change a few times a week.
_DEFAULT_EVERY_MINUTES = 60
# Every link on the page must be remembered, or an old one sliding into view looks new.
_MAX_PER_PAGE = 500


def links_on(html: str, page_url: str, pattern: str) -> list[tuple[str, str]]:
    """Every (address, link text) on the page whose address matches the source's pattern."""
    from bs4 import BeautifulSoup

    wanted = re.compile(pattern)
    found: dict[str, str] = {}
    for tag in BeautifulSoup(html or "", "lxml").find_all("a", href=True):
        parts = urlsplit(urljoin(page_url, tag["href"].strip()))
        url = f"{parts.scheme}://{parts.netloc}{parts.path}".rstrip("/")
        if not wanted.match(url):
            continue
        text = " ".join(tag.get_text(" ", strip=True).split())
        # The same story is often linked twice: keep the more descriptive text.
        if len(text) > len(found.get(url, "")):
            found[url] = text
        else:
            found.setdefault(url, text)
    return list(found.items())[:_MAX_PER_PAGE]


def _title(url: str, text: str) -> str:
    """The link text, or the address's last part when the link is only a picture."""
    if len(text) >= 12:
        return text[:300]
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"[-_]+", " ", slug).strip().capitalize() or url


async def read_page(source: dict) -> tuple[list[tuple[str, str]], str]:
    """(story links, "plain" | "browser"). Empty when neither way found any."""
    _, html = await article._plain(source["url"])
    found = links_on(html, source["url"], source["link_pattern"])
    if found:
        return found, "plain"
    _, html = await article._browser(source["url"])
    return links_on(html, source["url"], source["link_pattern"]), "browser"


def _due(row, every_minutes: int) -> bool:
    if not row["last_checked_at"]:
        return True
    checked = datetime.fromisoformat(row["last_checked_at"])
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - checked >= timedelta(minutes=every_minutes)


async def execute() -> list[Article]:
    """Read every page source that is due. On a page's first look, everything is baseline."""
    rows = {row["name"]: row for row in db.get_enabled_sources()}
    collected: list[Article] = []
    for source in config.SOURCES:
        row = rows.get(source["name"])
        if source.get("kind") != "page" or row is None:
            continue
        if not _due(row, source.get("every_minutes", _DEFAULT_EVERY_MINUTES)):
            continue
        try:
            found, how = await read_page(source)
        except Exception as error:  # noqa: BLE001 - one bad page must not stop the rest
            found, how = [], f"crashed: {error}"
        if not found:
            failures = db.record_source_failure(source["name"], f"no story links ({how})")
            log.warning("Page '%s' gave no story links (%s in a row)", source["name"], failures)
            if failures == 5:
                from utils import telegram_error
                telegram_error.send_error(
                    f"Page '{source['name']}' has shown no story links 5 times in a row. "
                    f"The site may have changed its layout.", node_name="fetch_pages")
            continue

        first_look = not row["last_ok_at"]
        db.record_source_success(source["name"], "", "")
        new = [(url, text) for url, text in found
               if not db.item_seen("rss", textclean.normalise_url(url))]
        log.info("Page '%s' read via %s: %d story links, %d new%s", source["name"], how,
                 len(found), len(new), " (first look: recorded, not queued)" if first_look else "")
        for url, text in new:
            # A listing link is often just a name; the sorter needs the page behind it.
            summary = "" if first_look else (await _page_text(url))[:config.MAX_BODY_CHARS]
            collected.append(Article(source_name=source["name"], topic=source["topic"],
                                     url=url, title=_title(url, text), summary=summary,
                                     published=None, baseline=first_look))
    return collected


async def _page_text(url: str) -> str:
    """The readable text of a story's own page, plain request first. "" if neither works."""
    text, _ = await article._plain(url)
    if text is None:
        text, _ = await article._browser(url)
    return text or ""
