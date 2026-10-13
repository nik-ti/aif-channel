"""Finds where to try a new product, for a post whose source is a tweet or an aggregator page
(AI/TLDR) with no link to the thing itself.

Only a product a person can go and use gets a link: an announcement is just reported,
since the post already says what the article would (nikita, 2026-10-09). The first search
mostly finds news about the product, so a second one searches for it by name. Only an address
the search really returned is used; an announcement page counts only for its "try it" link.
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

Only a NEW product or tool that a person can go and use gets one. A feature update, an
announcement, research, a deal, a policy or pricing does not.

Answer in exactly two lines:
NAME: the product's name, or NONE if it is not a new product a person can use
URL: from the search results, the page its MAKERS publish where a person can try, use, sign up
for or download it (a demo, app, playground or download page; for a free or open-source project
with no site of its own, its code on GitHub). NONE if every result is news, a blog post, a
video or a forum thread ABOUT it: never answer with one of those, never x.com or twitter.com.
The page must be about THIS product, not an earlier one: check its date."""

# The first search mostly finds news ABOUT the product (devops.com, three times out of three
# for the Adobe clones, 2026-10-13). The second searches for the product itself by name.
SEARCH_AGAIN = """Answer with ONE URL from the search results: the page the makers of the product
below publish, where a person can try, use or download it (their own site, a download or try
page, or its code on GitHub). Answer NONE if no result is theirs. Never a news site, blog post,
video or forum thread about it.

The product: {name}. What the post says about it: {post}"""

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


def _line(answer: str, label: str) -> str:
    """The value after "LABEL:" in the model's answer, or ""."""
    match = re.search(rf"(?im)^\s*{label}\s*:\s*(.+)$", answer or "")
    value = match.group(1).strip() if match else ""
    return "" if value.upper().startswith("NONE") else value


def _clean(url: str) -> str:
    """The address without its query or fragment: a found link came with a referral code once
    (getartcraft.com/?r=..., 2026-10-13)."""
    return url.split("#", 1)[0].split("?", 1)[0]


def _among(url: str, pages: list[str]) -> bool:
    """True if the search really returned this address (or a page inside it)."""
    url = _clean(url).rstrip("/")
    return any(_clean(page).rstrip("/") == url or _clean(page).startswith(url + "/")
               for page in pages)


async def _checked(item_id: int, url: str, pages: list[str]) -> str:
    """The address if it is a real page by the makers, else "".

    An announcement page counts only for the "try it" link on it, and only when it is
    current (a fresh Managed Agents tweet once got a May blog post, 2026-10-09). A product's
    own page is taken as it is: its "Launch App" button can be a different product
    (ArtCraft's image tool instead of its Adobe clones), and a date on it is usually an
    earlier version's.
    """
    if not _among(url, pages):
        log.info("Rejected found link for item %s: not among the search results (%s)",
                 item_id, url[:100])
        return ""
    url = _clean(url)
    final, html = await _loads(url)
    if not final or publisher.is_x_link(url) or publisher.is_x_link(final):
        log.info("Rejected found link for item %s: %s", item_id, url[:100])
        return ""
    if not article.is_article_url(final):
        return url
    dated = article.page_date(html)
    if article.is_old(dated, config.LINK_MAX_AGE_DAYS * 24):
        log.info("Rejected found link for item %s: page dated %s (%s)",
                 item_id, f"{dated:%Y-%m-%d}", url[:100])
        return ""
    demo = demo_link(html, final)
    if demo and (await _loads(demo))[0]:
        return _clean(demo)
    log.info("Rejected found link for item %s: an article, not the product (%s)",
             item_id, url[:100])
    return ""


async def find(item, post_html: str) -> str:
    """Where to try the product this post is about, or "" when it is not one or none was found.

    Two searches at most (~2 cents each): the post and its source, then the product's name.
    """
    post = persona_loader.visible_text(post_html)
    user = (f"Today is {datetime.now(timezone.utc):%Y-%m-%d}.\n\n"
            f"The post:\n{post}\n\n"
            f"What it was written from:\n{article.full_source(item)[:2000]}")
    try:
        answer, pages = await openrouter.web_search(
            model=config.LINK_FINDER_MODEL, system=PROMPT, user=user)
        name = _line(answer, "NAME")
        if not name:
            log.info("No product to link for item %s", item["id"])
            return ""
        match = _URL.search(_line(answer, "URL"))
        url = await _checked(item["id"], match.group(0).rstrip(".,;"), pages) if match else ""
        if not url:
            first_line = post.strip().splitlines()[0] if post.strip() else ""
            answer, pages = await openrouter.web_search(
                model=config.LINK_FINDER_MODEL,
                system=SEARCH_AGAIN.format(name=name, post=first_line[:200]),
                user=f"{name}: official site, download page or GitHub")
            match = _URL.search(answer or "")
            url = await _checked(item["id"], match.group(0).rstrip(".,;"), pages) if match else ""
    except openrouter.LLMError as error:
        log.warning("Link search failed for item %s: %s", item["id"], error)
        return ""

    if not url:
        log.info("No official page found for item %s", item["id"])
        return ""
    log.info("Found where to try it for item %s: %s", item["id"], url[:100])
    db.set_item_link(item["id"], url)
    return url
