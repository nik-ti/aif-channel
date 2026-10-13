"""Tests for the lab sources added 2026-10-13 (SPEC.md, "More lab sources").

No network: feeds are faked. They check that a new feed's first read is recorded but never
queued, that later reads queue as before, that the page patterns take stories and skip
navigation, that the new X accounts are configured, and that reader failures are visible.
Run: /usr/bin/python3 tests/test_new_sources.py
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

config.DB_PATH = Path(tempfile.mkdtemp()) / "test.db"

from utils import db  # noqa: E402

db.init_db()
db.sync_sources(config.SOURCES)

PASSED: list[str] = []
FAILED: list[str] = []

UNDATED_FEED = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Old post one</title><link>https://developers.googleblog.com/old-one/</link>
<description>old</description></item>
<item><title>Old post two</title><link>https://developers.googleblog.com/old-two/</link>
<description>old</description></item>
</channel></rss>"""

NEWER_FEED = UNDATED_FEED.replace(
    "<item>", "<item><title>Brand new launch</title>"
    "<link>https://developers.googleblog.com/brand-new/</link><description>new</description></item><item>", 1)


def test(fn):
    """Run one test, sync or async, and record whether it passed."""
    try:
        result = fn()
        if asyncio.iscoroutine(result):
            asyncio.run(result)
        PASSED.append(fn.__name__)
    except Exception as error:  # noqa: BLE001
        FAILED.append(f"{fn.__name__}: {type(error).__name__} {error}")
    return fn


def _source(name: str) -> dict:
    return next(s for s in config.SOURCES if s["name"] == name)


def _row(name: str) -> dict:
    return dict(next(r for r in db.get_enabled_sources() if r["name"] == name))


async def _read_feed(name: str, xml: str):
    from nodes import fetch_rss

    async def fake_read(client, url, headers, max_bytes):
        return 200, {}, xml
    real, fetch_rss._read = fetch_rss._read, fake_read
    try:
        return await fetch_rss.fetch_one(None, _row(name))
    finally:
        fetch_rss._read = real


@test
def the_new_sources_are_configured():
    names = {s["name"] for s in config.SOURCES}
    assert {"google_dev", "google_ai", "microsoft_ai", "kimi_blog", "zai_models"} <= names, names
    assert {"openaidevs", "googleaidevs", "microsoftai"} <= set(config.X_ACCOUNTS)
    new = ("google_dev", "google_ai", "microsoft_ai", "kimi_blog", "zai_models", "openaidevs",
           "googleaidevs", "microsoftai")
    assert not [p for p in config.check() if any(n in p for n in new)], config.check()


@test
async def a_new_feeds_first_read_is_recorded_not_queued():
    from nodes import collect_loop
    articles, status = await _read_feed("google_dev", UNDATED_FEED)
    assert status == "ok" and len(articles) == 2
    assert all(a.baseline for a in articles), [a.baseline for a in articles]
    for article in articles:
        collect_loop._store_article(article)
    queued = db.conn().execute("SELECT COUNT(*) FROM items WHERE source_name = 'google_dev' "
                               "AND status = 'queued'").fetchone()[0]
    assert queued == 0, queued


@test
async def after_the_first_read_new_posts_are_queued():
    from nodes import collect_loop
    articles, _ = await _read_feed("google_dev", NEWER_FEED)
    assert not any(a.baseline for a in articles)
    stored = [collect_loop._store_article(a) for a in articles]
    queued = db.conn().execute("SELECT title FROM items WHERE source_name = 'google_dev' "
                               "AND status = 'queued'").fetchall()
    assert [r[0] for r in queued] == ["Brand new launch"], (stored, [r[0] for r in queued])


@test
async def a_feed_read_before_keeps_queueing_as_it_always_did():
    db.conn().execute("UPDATE sources SET last_ok_at = '2026-10-01 00:00:00' WHERE name = 'openai'")
    db.conn().commit()
    articles, _ = await _read_feed("openai", UNDATED_FEED.replace("developers.googleblog.com", "openai.com"))
    assert articles and not any(a.baseline for a in articles)


@test
def the_page_patterns_take_stories_and_skip_navigation():
    cases = {
        "kimi_blog": (["https://www.kimi.com/blog/kimi-k3", "https://www.kimi.com/blog/agent-swarm"],
                      ["https://www.kimi.com/blog", "https://www.kimi.com/en"]),
        "microsoft_ai": (["https://microsoft.ai/news/introducing-mai-thinking-1"],
                         ["https://microsoft.ai/news", "https://microsoft.ai/about"]),
        "zai_models": (["https://docs.z.ai/guides/llm/glm-5.3", "https://docs.z.ai/guides/vlm/glm-5.3-flash",
                        "https://docs.z.ai/guides/image/glm-image"],
                       ["https://docs.z.ai/guides/overview/quick-start", "https://docs.z.ai/api-reference/introduction"]),
    }
    for name, (stories, navigation) in cases.items():
        pattern = re.compile(_source(name)["link_pattern"])
        assert all(pattern.match(u) for u in stories), (name, [u for u in stories if not pattern.match(u)])
        assert not any(pattern.match(u) for u in navigation), (name, [u for u in navigation if pattern.match(u)])


@test
async def a_reader_failure_is_logged_where_it_can_be_seen():
    import httpx
    from nodes import article
    seen: list[logging.LogRecord] = []

    class Catch(logging.Handler):
        def emit(self, record):
            seen.append(record)

    handler = Catch(level=logging.WARNING)
    article.log.addHandler(handler)

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return httpx.Response(429, request=httpx.Request("GET", url))
    real, httpx.AsyncClient = httpx.AsyncClient, FakeClient
    try:
        assert await article._reader("https://example.com/page") is None
    finally:
        httpx.AsyncClient = real
        article.log.removeHandler(handler)
    assert any("429" in r.getMessage() for r in seen), [r.getMessage() for r in seen]


print(f"{len(PASSED)} passed, {len(FAILED)} failed")
for line in FAILED:
    print("  FAIL", line[:240])
sys.exit(1 if FAILED else 0)
