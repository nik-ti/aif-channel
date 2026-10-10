"""Finds where to try a new product, for a post whose source is a tweet with no outside link.

Only a product a person can go and use gets a link: an announcement is just reported,
since the post already says what the article would (nikita, 2026-10-09). A model searches
the web for the demo, app or download page. An announcement page counts only for the
"try it" link on it; otherwise the post goes out with no link line.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

import config
from nodes import article, publisher
from utils import db, logger as log_setup, openrouter, persona_loader

log = log_setup.get("link_finder")

PROMPT = """You decide whether a news post needs a link where the reader can try something.

Only if the post is about a NEW product or tool that a person can go and use, search the web
and answer with ONE URL and nothing else: the maker's own page where a person can try, use,
sign up for or download it (a demo, app, playground or download page).
Answer exactly NONE for anything else: a feature update, an announcement, research, a deal,
a policy, pricing. Answer NONE too if you cannot find such a page.
Never a blog post or announcement article, never x.com or twitter.com, never a news site
or aggregator. The page must be about THIS product, not an earlier one: check its date."""

_URL = re.compile(r"https?://[^\s<>\"')\]]+")
_ANCHOR = re.compile(r'<a\s[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_TRY_WORDS = re.compile(r"\b(try|demo|experience|playground|play|launch app|open app|get started)\b", re.I)
_TRY_HOSTS = article.TRY_HOSTS


def _site(url: str) -> str:
    """The last two parts of the host: odyssey.systems for experience.odyssey.systems."""
    host = urlparse(url).netloc.lower().split(":")[0]
    return ".".join(host.split(".")[-2:])


def demo_link(html: str, page_url: str) -> str:
    """A "try it" link on the maker's own site, found on its announcement page, or ""."""
    for href, text in _ANCHOR.findall(html or ""):
        if _site(href) != _site(page_url) or href.rstrip("/") == page_url.rstrip("/"):
            continue
        words = re.sub(r"<[^>]+>", " ", text)
        if urlparse(href).netloc.lower().startswith(_TRY_HOSTS) or _TRY_WORDS.search(words):
            return href
    return ""


async def _loads(url: str) -> tuple[str, str]:
    """(the address after redirects, the page), or ("", "") if it does not load."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15,
                                     headers={"User-Agent": "Mozilla/5.0"}) as client:
            reply = await client.get(url)
    except httpx.HTTPError:
        return "", ""
    # 401/403 is a bot wall on a real page (BLS, Cloudflare), not a dead link.
    if reply.status_code >= 400 and reply.status_code not in (401, 403):
        return "", ""
    return str(reply.url), reply.text


async def find(item, post_html: str) -> str:
    """Where to try the product this post is about, or "" when it is not one or none was found."""
    user = (f"Today is {datetime.now(timezone.utc):%Y-%m-%d}.\n\n"
            f"The post:\n{persona_loader.visible_text(post_html)}\n\n"
            f"What it was written from:\n{(item['body'] or '')[:2000]}")
    try:
        answer = await openrouter.chat_text(
            model=config.LINK_FINDER_MODEL, system=PROMPT, user=user,
            temperature=0.0, max_tokens=300, web_search=True)
    except openrouter.LLMError as error:
        log.warning("Link search failed for item %s: %s", item["id"], error)
        return ""

    match = _URL.search(answer or "")
    if not match:
        log.info("No official page found for item %s", item["id"])
        return ""
    url = match.group(0).rstrip(".,;")
    final, html = await _loads(url)
    if not final or publisher.is_x_link(url) or publisher.is_x_link(final):
        log.info("Rejected found link for item %s: %s", item["id"], url[:100])
        return ""
    dated = article.page_date(html)
    if article.is_old(dated, config.LINK_MAX_AGE_DAYS * 24):
        log.info("Rejected found link for item %s: page dated %s (%s)",
                 item["id"], f"{dated:%Y-%m-%d}", url[:100])
        return ""
    demo = demo_link(html, final)
    if demo and (await _loads(demo))[0]:
        url = demo
    elif article.is_article_url(final):
        log.info("Rejected found link for item %s: an announcement, not the product (%s)",
                 item["id"], url[:100])
        return ""
    log.info("Found where to try it for item %s: %s", item["id"], url[:100])
    db.set_item_link(item["id"], url)
    return url
