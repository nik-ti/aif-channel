"""Finds the real page for a post whose source is a tweet with no outside link.

A news account's tweet is never what "Try it here" should open, so before such a
post goes out, a model searches the web for the maker's own page (the demo, the
app, the announcement). When it lands on an announcement that links to the demo
on the maker's own site, the demo wins. The page must load and must not be on X;
otherwise the post goes out with no link line at all.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

import config
from nodes import publisher
from utils import db, logger as log_setup, openrouter, persona_loader

log = log_setup.get("link_finder")

PROMPT = """You find the official web page for an AI product that a news post is about.

Search the web, then answer with ONE URL and nothing else:
- best: the page where a person can try, use or download the product (a demo, app or playground)
- otherwise: the maker's own announcement or product page
Never a link to x.com or twitter.com, never a news site, blog or aggregator writing about it.
If you cannot find the maker's own page, answer exactly: NONE"""

_URL = re.compile(r"https?://[^\s<>\"')\]]+")
_ANCHOR = re.compile(r'<a\s[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_TRY_WORDS = re.compile(r"\b(try|demo|experience|playground|play|launch app|open app|get started)\b", re.I)
_TRY_HOSTS = ("experience.", "demo.", "try.", "play.", "playground.", "app.", "studio.", "chat.")


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
    """The maker's own page for this post, or "" when none was found and checked."""
    user = (f"The post:\n{persona_loader.visible_text(post_html)}\n\n"
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
    demo = demo_link(html, final)
    if demo and (await _loads(demo))[0]:
        url = demo
    log.info("Found the official page for item %s: %s", item["id"], url[:100])
    db.set_item_link(item["id"], url)
    return url
