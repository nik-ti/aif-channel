"""Tests for the AI news channel, with every model call faked.

They check the SPEC.md rules that do not depend on a model's judgement: the AI
prompts are its own, links and the signature are added in code, the sources
parse, and the channel reads only its own tweet-stream group.
Run: /usr/bin/python3 tests/test_ai_channel.py
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

config.DB_PATH = Path(tempfile.mkdtemp()) / "test.db"

from utils import db  # noqa: E402

db.init_db()

PASSED: list[str] = []
FAILED: list[str] = []


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


MARKETS_WORDS = re.compile(r"crypto|geopolit|scheduled release|forecast:|central bank|"
                           r"trader|payroll", re.IGNORECASE)


@test
def settings_are_complete_and_the_graph_compiles():
    assert config.check() == [], config.check()
    from pipeline import graph
    assert "video_analyst" in graph.graph.get_graph().nodes
    edges = {(e.source, e.target) for e in graph.graph.get_graph().edges}
    assert ("repeat_check", "image_analyst") in edges and ("image_analyst", "video_analyst") in edges


@test
def the_writer_prompt_is_this_channels_own():
    from nodes import writer
    prompt = writer.PROMPT.format(length_rule="L", emoji_rule=writer.EMOJI_RULE,
                                  today="4 October 2026", market_reading="")
    assert not MARKETS_WORDS.search(prompt), MARKETS_WORDS.search(prompt).group(0)
    assert 'href="LINK"' in prompt
    for mark in config.POST_MARKS:
        assert mark in writer.EMOJI_RULE


@test
def the_editor_prompt_and_rules_are_this_channels_own():
    from nodes import editor
    prompt = editor.PROMPT.format(today="4 October 2026", market_reading="")
    assert not MARKETS_WORDS.search(prompt), MARKETS_WORDS.search(prompt).group(0)
    assert not MARKETS_WORDS.search(editor.RULES["WRONG_TOPIC"])
    assert "JARGON" in editor.SCHEMA["properties"]["rules_broken"]["items"]["enum"]
    assert "JARGON" in prompt
    from pipeline import stations
    assert "JARGON" in stations.FIXABLE_RULES


@test
def no_emoji_survives_but_the_bullet_does():
    from nodes import writer
    assert config.POST_MARKS == {} and config.BULLET == "•"
    text, kept = writer.enforce_mark("🎨 <b>ChatGPT can draw from sketches</b> 🔥")
    assert kept == "" and text == "<b>ChatGPT can draw from sketches</b>", text
    text, kept = writer.enforce_mark("🇺🇸 <b>OpenAI ships a thing</b>")
    assert kept == "" and "🇺🇸" not in text
    text, kept = writer.enforce_mark("🛢️ <b>OpenAI ships a thing</b>")
    assert kept == "" and "🛢" not in text
    # The list bullet is layout, not a mark, and is kept.
    body = f"<b>Suno v6 is out</b>\n\n{config.BULLET} change one line\n{config.BULLET} free tier"
    assert writer.enforce_mark(body)[0].count(config.BULLET) == 2


@test
def a_post_ending_in_its_link_line_is_complete():
    from nodes import writer
    post = ('<b>ChatGPT can now turn sketches into pictures</b>\n\nIt is free.\n\n'
            '<a href="LINK">Try it here</a>')
    assert not writer._looks_incomplete(post)


@test
async def the_sorter_asks_who_can_use_it_and_none_caps_at_three():
    from nodes import sorter
    from utils import openrouter
    assert config.SORTER_AXIS in sorter.SCHEMA["properties"]
    assert "market" not in sorter.SCHEMA["properties"]
    assert "none" in config.SORTER_AXIS_VALUES

    async def fake(**kwargs):
        return {"relevant": True, "topic": config.VALID_TOPICS[0],
                config.SORTER_AXIS: "none", "importance": 5, "reason": "a paper"}
    real, openrouter.chat_json = openrouter.chat_json, fake
    try:
        item = {"id": 1, "title": "A paper", "body": "", "topic_hint": "", "origin": "rss",
                "source_name": "hf_blog", "calendar_title": ""}
        verdict = await sorter.execute(item)
    finally:
        openrouter.chat_json = real
    assert verdict["market"] == "none" and verdict["importance"] == 3, verdict


@test
def the_publisher_fills_the_link_and_signs_once():
    from nodes import publisher
    post = ('<b>A free icon pack</b>\n\n• 900 icons\n\n<a href="LINK">Grab it here</a>'
            ' and <a href="https://evil.example/ref">this</a>')
    config.SIGNATURE_HTML = '<a href="https://t.me/test_ai">Test AI | Subscribe</a>'
    out = publisher.compose(post, "https://ai-tldr.dev/releases/x/",
                            link_url="https://github.com/acme/icons")
    assert '<a href="https://github.com/acme/icons">Grab it here</a>' in out
    assert "evil.example" not in out and "this" in out
    assert out.count("Test AI | Subscribe") == 1 and out.rstrip().endswith("</a>")
    # No product link known: the item's own address.
    out = publisher.compose(post, "https://openai.com/index/x", link_url="")
    assert 'href="https://openai.com/index/x"' in out
    # The writer left the link line out: one is added, never zero.
    out = publisher.compose("<b>A free icon pack</b>", "https://openai.com/index/x", link_url="")
    assert out.count('href="https://openai.com/index/x"') == 1


@test
def links_in_a_post_lose_their_utm_parameters():
    from nodes import publisher
    from utils import textclean
    clean = textclean.strip_utm
    # Every utm_ parameter goes, in any case; everything else stays, in order.
    assert clean("https://x.ai/news/grok?utm_source=tldr&utm_medium=email") == "https://x.ai/news/grok"
    assert clean("https://youtube.com/watch?v=abc&UTM_Campaign=x&t=30") == "https://youtube.com/watch?v=abc&t=30"
    assert clean("https://a.dev/p?ref=hn&utm_source=x#install") == "https://a.dev/p?ref=hn#install"
    assert clean("https://a.dev/p") == "https://a.dev/p"
    assert clean("https://a.dev/p?") == "https://a.dev/p?"
    # In the finished post: the product link, a kept source link, and HTML-escaped &amp;.
    config.SIGNATURE_HTML = '<a href="https://t.me/x?utm_source=sig">Sub</a>'
    post = ('<b>New tool</b>\n\n<a href="LINK">Try it here</a> and '
            '<a href="https://github.com/a/tool/releases?page=2&amp;utm_source=feed">the releases</a>')
    out = publisher.compose(post, "https://ai-tldr.dev/x?utm_source=rss",
                            link_url="https://github.com/a/tool?utm_source=ai-tldr&tab=readme")
    assert 'href="https://github.com/a/tool?tab=readme"' in out, out
    assert 'href="https://github.com/a/tool/releases?page=2"' in out, out
    # No product link: the item's own address, cleaned too.
    out = publisher.compose('<b>New tool</b>\n\n<a href="LINK">Read it</a>',
                            "https://openai.com/index/x?utm_source=rss&utm_medium=feed", link_url="")
    assert 'href="https://openai.com/index/x"' in out, out
    assert "utm_" not in out.replace(config.SIGNATURE_HTML, ""), out
    assert config.SIGNATURE_HTML in out          # the channel's own signature is left as written


@test
def atom_related_links_and_the_byte_cap():
    from nodes import fetch_rss
    entry = ('<entry><title>Acme Icons</title><link href="https://tom.example/2026/acme.html"/>'
             '<link rel="related" type="text/html" href="https://github.com/acme/icons"/>'
             '<updated>2026-10-04T10:00:00+00:00</updated><content type="html">Icons.</content></entry>')
    feed = ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
            + entry * 50 + "</feed>")
    articles = fetch_rss._parse_feed(feed, "tom_doerr", "tool")
    assert articles[0].url == "https://tom.example/2026/acme.html"
    assert articles[0].link_url == "https://github.com/acme/icons"
    cut = fetch_rss.trim_to_whole_entries(feed[: len(feed) // 3].encode())
    assert len(fetch_rss._parse_feed(cut, "tom_doerr", "tool")) >= 10


@test
def the_product_link_comes_from_an_aggregator_page():
    from nodes import article
    html = ('<html><body><nav><a href="https://ai-tldr.dev/tools">Tools</a></nav><main>'
            '<h1>Claude Code 2.1.289</h1><p>Text</p>'
            '<a href="/releases/other/">Related</a>'
            '<a href="https://github.com/anthropics/claude-code/releases/tag/v2.1.289">Release Notes</a>'
            '<a href="https://code.claude.com/docs/en/changelog">Changelog</a></main></body></html>')
    link = article.product_link(html, "https://ai-tldr.dev/releases/anthropic-claude-code/")
    assert link == "https://github.com/anthropics/claude-code/releases/tag/v2.1.289", link
    assert article.product_link(html, "https://openai.com/index/x") == ""


@test
def the_product_link_reaches_the_folded_story():
    item_id = db.insert_item(origin="rss", source_name="tom_doerr", external_id="e1",
                             url="https://tom.example/a.html", title="Acme Icons",
                             body="Icons.", topic_hint="tool",
                             link_url="https://github.com/acme/icons")
    row = db.get_item(item_id)
    assert row["link_url"] == "https://github.com/acme/icons"
    from datetime import datetime, timezone
    from nodes import stories
    story = stories.Story(id=0, headline="Acme Icons", summary="Acme Icons")
    story.absorb(dict(row), datetime.now(timezone.utc))
    assert stories.as_source(story)["link_url"] == "https://github.com/acme/icons"


RELAY_ACCOUNTS = Path("/home/nikita/systems/infra/tweet-relay/accounts.txt")


@test
def the_channel_follows_exactly_the_relays_accounts():
    from nodes import collect_loop
    assert config.TWEET_STREAM_GROUP != "news-channel"      # its own bookmark on the shared stream
    assert collect_loop.reads_tweets()
    assert all(h == h.lower() for h in config.X_ACCOUNTS)
    assert all(t in config.VALID_TOPICS for t in config.X_ACCOUNTS.values())
    if RELAY_ACCOUNTS.exists():                             # on the VPS: the two lists must agree
        relay = {line.strip().lower() for line in RELAY_ACCOUNTS.read_text().splitlines()
                 if line.strip() and not line.startswith("#")}
        assert relay == set(config.X_ACCOUNTS), (relay, set(config.X_ACCOUNTS))


@test
def a_tweet_matches_its_account_whatever_the_capitals():
    import json
    from nodes import fetch_tweets
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    def entry(handle):
        return {"data": json.dumps({"tweet_id": handle + "1", "handle": handle, "text": "New model",
                                    "created_at": now, "url": f"https://x.com/{handle}/status/1"})}
    tweets = [fetch_tweets._parse_entry(entry(h)) for h in ("OpenAI", "GoogleDeepMind", "DeItaone")]
    assert tweets[0].handle == "openai" and tweets[0].url == "https://x.com/OpenAI/status/1"
    kept = fetch_tweets._filter_batch(tweets)
    assert [t.handle for t in kept] == ["openai", "googledeepmind"]      # a market account is not ours


@test
def feed_dates_get_two_days():
    assert config.ARTICLE_MAX_AGE_HOURS == 48


@test
def every_source_has_a_known_topic_and_the_big_feed_is_capped():
    names = {s["name"] for s in config.SOURCES}
    assert {"ai_tldr", "openai", "anthropic", "tom_doerr", "futuretools"} <= names, names
    tom = next(s for s in config.SOURCES if s["name"] == "tom_doerr")
    assert 0 < tom["max_bytes"] <= 2_000_000



# ── Pages without a feed (nodes/fetch_pages.py) ──

LISTING = ('<html><body><nav><a href="/news">News</a><a href="/careers">Jobs</a></nav><main>'
           '<a href="/news/grok-5">Grok 5 is here</a>'
           '<a href="https://acme.ai/news/voice-mode">Voice mode for everyone</a>'
           '<a href="/news/grok-5#comments">comments</a></main></body></html>')
PAGE = {"name": "acme_news", "kind": "page", "topic": "launch",
        "url": "https://acme.ai/news", "link_pattern": r"^https://acme\.ai/news/[a-z0-9-]+$"}


@test
def a_listing_page_gives_its_story_links_once_each():
    from nodes import fetch_pages
    found = fetch_pages.links_on(LISTING, PAGE["url"], PAGE["link_pattern"])
    assert found == [("https://acme.ai/news/grok-5", "Grok 5 is here"),
                     ("https://acme.ai/news/voice-mode", "Voice mode for everyone")], found


@test
async def a_page_that_comes_back_as_junk_is_read_with_the_browser():
    from nodes import article, fetch_pages
    calls = []

    async def plain(url):
        calls.append("plain")
        return None, "<html><body>Checking your browser…</body></html>"

    async def browser(url):
        calls.append("browser")
        return None, LISTING
    real = article._plain, article._browser
    article._plain, article._browser = plain, browser
    try:
        found, how = await fetch_pages.read_page(PAGE)
    finally:
        article._plain, article._browser = real
    assert calls == ["plain", "browser"] and how == "browser" and len(found) == 2


@test
async def the_first_look_at_a_page_queues_nothing_and_the_next_finds_whats_new():
    from nodes import article, collect_loop, fetch_pages
    page = dict(PAGE, name="acme_first")
    real_sources = list(config.SOURCES)
    config.SOURCES[:] = [page]
    db.sync_sources(config.SOURCES)
    html = {"now": LISTING}

    async def plain(url):
        if url == page["url"]:
            return None, html["now"]
        return "The story page, long enough to read.", ""
    real = article._plain
    article._plain = plain
    try:
        first = [a for a in await fetch_pages.execute() if a.source_name == "acme_first"]
        assert first and all(a.baseline for a in first)
        assert sum(collect_loop._store_article(a) for a in first) == 0
        html["now"] = LISTING.replace("</main>", '<a href="/news/sora-3">Sora 3 makes longer videos</a></main>')
        db.conn().execute("UPDATE sources SET last_checked_at = NULL WHERE name = 'acme_first'")
        second = [a for a in await fetch_pages.execute() if a.source_name == "acme_first"]
        assert not any(a.baseline for a in second)
        assert sum(collect_loop._store_article(a) for a in second) == 1
        assert second[0].summary == "The story page, long enough to read."
    finally:
        article._plain = real
        config.SOURCES[:] = real_sources
    queued = db.conn().execute("SELECT title FROM items WHERE source_name = 'acme_first' "
                               "AND status = 'queued'").fetchall()
    assert [r["title"] for r in queued] == ["Sora 3 makes longer videos"], [tuple(r) for r in queued]


@test
def the_feed_reader_leaves_pages_alone():
    from nodes import fetch_rss
    rows = [{"name": "a", "kind": "page"}, {"name": "b", "kind": "rss"}]
    assert [r["name"] for r in fetch_rss.feeds_only(rows)] == ["b"]


@test
async def an_article_both_readers_fail_on_goes_through_the_reader_service():
    from nodes import article
    assert config.READER_FALLBACK_URL.startswith("https://")
    seen = []

    async def blocked(url):
        return None, "<html>Just a moment...</html>"

    class Reply:
        status_code = 200
        text = ("Title: GPT-6.1 Sol\n\nURL Source: https://openai.com/x\n\nMarkdown Content:\n"
                + "GPT-6.1 Sol is cheaper. " * 40)

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *exc): return False
        async def get(self, url):
            seen.append(url)
            return Reply()
    real = article._plain, article._browser, article.httpx.AsyncClient
    article._plain, article._browser, article.httpx.AsyncClient = blocked, blocked, Client
    try:
        text = await article._reader("https://openai.com/x")
    finally:
        article._plain, article._browser, article.httpx.AsyncClient = real
    assert seen == [config.READER_FALLBACK_URL + "https://openai.com/x"]
    assert text.startswith("GPT-6.1 Sol is cheaper.") and "URL Source" not in text


@test
def the_sorter_is_told_the_date():
    from nodes import sorter
    assert config.SORTER_SHOWS_DATE
    message = sorter.user_message({"title": "DevDay 2026 recap", "body": "", "topic_hint": "",
                                   "origin": "rss", "source_name": "openai", "calendar_title": ""})
    assert message.startswith("Today is ")


@test
def the_link_line_always_ends_the_post():
    from nodes import writer
    post = ('<b>Claude Code saves your work</b>\n\nIt resumes.\n\n<a href="LINK">Read it here</a>'
            '\n\nGreat for teams.')
    fixed = writer.link_line_last(post)
    assert fixed.endswith('<a href="LINK">Read it here</a>'), fixed
    assert "Great for teams." in fixed and fixed.count("LINK") == 1


# ── Media from video players and blocked pages ──

PLAYER_PAGE = ('<html><head><meta property="og:image" content="https://img.example/card.png"></head>'
               '<body><main><iframe src="https://player.vimeo.com/video/1230606080?h=ae5fad6134&amp;badge=0">'
               '</iframe><script>{"u":"https:\\/\\/www.youtube.com\\/embed\\/dQw4w9WgXcQ?rel=0"}</script>'
               '<a href="https://www.youtube.com/OpenAI">channel</a></main></body></html>')


@test
def video_players_on_a_page_become_clip_candidates():
    from nodes import media
    images, videos = media.from_article_html(PLAYER_PAGE, "https://openai.com/index/dots/")
    urls = [v["url"] for v in videos]
    assert "https://player.vimeo.com/video/1230606080?h=ae5fad6134" in urls, urls
    assert "https://www.youtube.com/embed/dQw4w9WgXcQ" in urls, urls
    assert all(v["kind"] == "embed" for v in videos)
    assert images == ["https://img.example/card.png"]


@test
async def a_player_clip_is_fetched_with_the_downloader():
    from nodes import video_analyst
    from utils import embeds
    tmp = Path(tempfile.mkdtemp()) / "clip.mp4"
    tmp.write_bytes(b"\x00" * 1000)
    asked = []

    def fake(url, max_mb):
        asked.append(url)
        return tmp
    real = embeds.download
    embeds.download = fake
    try:
        saved = await video_analyst._download({"url": "https://player.vimeo.com/video/1?h=a", "kind": "embed"})
    finally:
        embeds.download = real
    assert asked == ["https://player.vimeo.com/video/1?h=a"] and saved == (tmp, 1000, "https://player.vimeo.com/video/1?h=a")


@test
async def a_blocked_page_read_by_the_reader_still_gives_its_pictures():
    from nodes import article
    seen = []

    async def blocked(url):
        return None, ""

    async def reader(url):
        return "The article text. " * 40

    async def reader_html(url):
        seen.append(url)
        return PLAYER_PAGE
    real = article._plain, article._browser, article._reader, article._reader_html
    article._plain, article._browser, article._reader, article._reader_html = blocked, blocked, reader, reader_html
    item_id = db.insert_item(origin="rss", source_name="openai", external_id="dots",
                             url="https://openai.com/index/dots/", title="Introducing dots")
    try:
        await article.fetch_for(dict(db.get_item(item_id)))
    finally:
        article._plain, article._browser, article._reader, article._reader_html = real
    stored = json.loads(db.get_item(item_id)["media_json"])
    assert seen == ["https://openai.com/index/dots/"]
    assert stored["images"] == ["https://img.example/card.png"] and len(stored["videos"]) == 2


# ── The editor remembers what it asked for ──

@test
async def on_a_rewrite_the_editor_sees_its_own_earlier_reason():
    from nodes import editor
    from utils import openrouter
    seen = {}

    async def fake(**kwargs):
        seen["user"] = kwargs["user"]
        return {"verdict": "approve", "rules_broken": [], "reason": "ok", "confidence": 1.0}
    real, openrouter.chat_json = openrouter.chat_json, fake
    item = {"id": 1, "source_name": "openai", "title": "GPT-6.1 Sol", "body": "text",
            "topic": "launch", "topic_hint": "launch", "calendar_title": ""}
    try:
        await editor.execute(item, "<b>Post</b>", 0, record=False, attempt=2,
                             previous_reason="say 'units of text' instead of 'tokens'")
        with_memory = seen["user"]
        await editor.execute(item, "<b>Post</b>", 0, record=False, attempt=1)
        without = seen["user"]
    finally:
        openrouter.chat_json = real
    assert "say 'units of text' instead of 'tokens'" in with_memory
    assert "YOUR EARLIER REJECTION" in with_memory and "YOUR EARLIER REJECTION" not in without


@test
def the_graph_carries_the_earlier_reason_to_the_second_check():
    from pipeline import graph
    assert "previous_editor_reason" in graph.BrainState.__annotations__
    assert config.EDITOR_REMEMBERS_REWRITES


@test
def tokens_are_not_jargon_here():
    from nodes import editor
    prompt = editor.PROMPT.format(today="4 October 2026", market_reading="")
    must_catch = prompt[prompt.index("MUST be caught"):prompt.index("Everyday tech words")]
    assert "token" not in must_catch.lower(), must_catch
    assert "tokens" in prompt[prompt.index("Everyday tech words"):]
    assert "show_hn" not in {s["name"] for s in config.SOURCES}



@test
def the_downloader_is_found_without_a_login_shell_and_failing_downloads_raise_an_alarm():
    import subprocess
    from utils import embeds, telegram_error
    assert Path(embeds.YTDLP).exists(), embeds.YTDLP
    alerts = []

    def broken(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "yt-dlp", stderr="ERROR: Unsupported URL")
    real_run, real_send = embeds.subprocess.run, telegram_error.send_error
    embeds.subprocess.run = broken
    telegram_error.send_error = lambda text, node_name="": alerts.append(text)
    embeds._failures = 0
    try:
        for _ in range(embeds.ALERT_AFTER_FAILURES):
            assert embeds.download("https://player.vimeo.com/video/1", 20) is None
    finally:
        embeds.subprocess.run, telegram_error.send_error = real_run, real_send
    assert len(alerts) == 1 and "yt-dlp" in alerts[0], alerts



@test
def a_third_partys_article_is_never_written_as_just_released():
    assert "mindstudio" not in {s["name"] for s in config.SOURCES}
    from nodes import editor, writer
    w = writer.PROMPT
    assert "## When it happened" in w and "just launched" in w
    e = editor.PROMPT.format(today="4 October 2026", market_reading="")
    assert "TIMING" in e and "just launched" in e



@test
async def the_article_is_read_before_the_sorter_judges():
    from pipeline import graph, stations
    edges = {(e.source, e.target) for e in graph.graph.get_graph().edges}
    assert ("fetch_article", "labeler") in edges and ("labeler", "sorter") in edges
    from nodes import article, sorter

    async def fetched(item):
        db.set_article_text(item["id"], "Suno Speech makes voice and music together. " * 30)
        return "Suno Speech makes voice and music together. " * 30
    real = article.fetch_for
    article.fetch_for = fetched
    item_id = db.insert_item(origin="rss", source_name="futuretools", external_id="suno",
                             url="https://suno.com/blog/speech", title="Suno Launches Speech Beta",
                             body="Source: suno.com | Release date: 2026-10-02")
    try:
        state = await stations.fetch_article_node({"item": dict(db.get_item(item_id))})
    finally:
        article.fetch_for = real
    message = sorter.user_message(state["item"])
    assert "Suno Speech makes voice and music together." in message, message[:300]
    assert "Release date: 2026-10-02" in message



# ── 2026-10-06: date in every call, daily limits per type, varied openings ──

@test
async def every_model_call_is_told_the_date_and_time():
    from utils import openrouter
    sent = []

    async def fake_post(payload):
        sent.append(payload["messages"][-1]["content"])
        return {"choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}]}
    real = openrouter._post
    openrouter._post = fake_post
    try:
        await openrouter.chat_text(model="m", system="s", user="hello")
        await openrouter.chat_json(model="m", system="s", user="hello")
        await openrouter.chat_json(model="m", system="s", user=[{"type": "text", "text": "look"}])
    finally:
        openrouter._post = real
    assert sent[0].startswith("Current date and time: ") and sent[0].endswith("hello"), sent[0]
    assert sent[1].startswith("Current date and time: ")
    assert sent[2][0]["text"].startswith("Current date and time: ") and sent[2][1]["text"] == "look"


def _sent_post(topic: str, minutes_ago: int) -> None:
    n = db.conn().execute("SELECT COUNT(*) FROM items").fetchone()[0]
    item_id = db.insert_item(origin="rss", source_name="t", external_id=f"cap{n}",
                             url=f"https://e.x/{n}", title=f"t{n}", topic_hint=topic)
    post_id = db.create_post(item_id=item_id, topic=topic, post_html="<b>x</b>",
                             image_url="", writer_model="t")
    db.conn().execute("UPDATE posts SET status='sent', sent_at=datetime('now', ?) WHERE id=?",
                      (f"-{minutes_ago} minutes", post_id))
    db.conn().commit()


@test
def guides_and_skills_are_capped_per_day_and_spaced_out():
    from pipeline import stations
    assert config.TOPIC_LIMITS["guide"][0] == 2
    assert config.TOPIC_LIMITS["skill"][0] == 2
    db.conn().execute("DELETE FROM posts"); db.conn().commit()
    assert stations.topic_limit_reason("skill") == ""
    _sent_post("skill", 30)
    assert "hours" in stations.topic_limit_reason("skill")            # too soon after the last one
    db.conn().execute("UPDATE posts SET sent_at=datetime('now','-5 hours')"); db.conn().commit()
    assert stations.topic_limit_reason("skill") == ""                 # spaced enough, 1 of 2 today
    _sent_post("skill", 300)
    assert "2 a day" in stations.topic_limit_reason("skill")          # the day's two are used
    assert stations.topic_limit_reason("feature") == ""               # features are not limited


@test
def an_opening_a_recent_post_already_used_is_caught():
    from nodes import writer
    recent = ["Here's a structured way to edit your marketing copy\n\nIt is a framework.",
              "Suno now makes spoken audio\n\nIt's called Speech."]
    assert writer.repeated_opening("<b>Here’s a free guide to AI search</b>\n\nText.", recent)
    assert writer.repeated_opening("<b>Suno now writes lyrics too</b>", recent)
    assert not writer.repeated_opening("<b>Designers get a free icon pack</b>", recent)



# ── The reserve: capped guides and skills wait, the best one posts when a slot opens ──

def _capped(title: str, topic: str, importance: int, hours_ago: int) -> int:
    n = db.conn().execute("SELECT COUNT(*) FROM items").fetchone()[0]
    item_id = db.insert_item(origin="rss", source_name="skills_trending", external_id=f"res{n}",
                             url=f"https://skills.sh/a/b/{n}", title=title, body="text",
                             topic_hint=topic, status="capped", status_reason="daily limit")
    db.conn().execute("UPDATE items SET topic=?, importance=?, fetched_at=datetime('now', ?) "
                      "WHERE id=?", (topic, importance, f"-{hours_ago} hours", item_id))
    db.conn().commit()
    return item_id


@test
async def the_reserve_drops_old_ones_and_releases_the_best_when_a_slot_opens():
    from nodes import reserve
    from utils import openrouter
    db.conn().execute("DELETE FROM posts"); db.conn().execute("DELETE FROM items WHERE status='capped'")
    db.conn().commit()
    old = _capped("Old skill", "skill", 5, 4 * 24)
    a = _capped("Skill A", "skill", 4, 5)
    b = _capped("Skill B", "skill", 4, 2)
    asked = {}

    async def fake(**kwargs):
        asked["user"] = kwargs["user"]
        return {"best": 1, "reason": "B is the most useful"}
    real, openrouter.chat_json = openrouter.chat_json, fake
    try:
        chosen = await reserve.next_release()
    finally:
        openrouter.chat_json = real
    assert db.get_item(old)["status"] == "expired"
    # Listed best score first, then newest: [0] Skill B, [1] Skill A. The model picked 1.
    assert chosen is not None and chosen["id"] == a, chosen and chosen["id"]
    assert "[0] Skill B" in asked["user"] and "Old skill" not in asked["user"]
    assert db.get_item(b)["status"] == "capped"                               # still waiting

    _sent_post("skill", 10)                                                   # slot taken again
    assert await reserve.next_release() is None


@test
async def a_released_item_skips_the_sorter_and_the_limit():
    from pipeline import stations
    item_id = _capped("Skill C", "skill", 4, 1)
    _sent_post("skill", 5)                       # the limit would refuse it now
    state = await stations.sorter_node({"item": dict(db.get_item(item_id)), "released": True})
    assert not state.get("outcome"), state
    assert state["sorter_verdict"]["topic"] == "skill"
    from pipeline import graph
    assert "released" in graph.BrainState.__annotations__

TWEET_NOW = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()


def _relay_entry(**over):
    data = {"tweet_id": "501", "handle": "OpenAI", "created_at": TWEET_NOW,
            "url": "https://x.com/OpenAI/status/501",
            "text": "Codex now reviews your pull requests. Details https://t.co/aaa",
            "media": ["https://pbs.twimg.com/media/own.jpg"], "video": "", "video_kind": "",
            "links": [{"url": "https://openai.com/index/codex-review/", "short": "https://t.co/aaa",
                       "title": "Codex reviews PRs", "description": "Turn on automatic review"}],
            "shared": None}
    data.update(over)
    return {"data": json.dumps(data)}


SHARED = {"kind": "quoted", "tweet_id": "99", "handle": "OpenAIDevs", "created_at": TWEET_NOW,
          "url": "https://x.com/OpenAIDevs/status/99",
          "text": "Background mode is live in the Responses API https://t.co/ddd",
          "links": [{"url": "https://platform.openai.com/docs/background", "short": "https://t.co/ddd",
                     "title": "", "description": ""},
                    {"url": "https://x.com/OpenAI/status/1", "short": "https://t.co/eee",
                     "title": "", "description": ""}],
          "media": ["https://pbs.twimg.com/media/q.jpg"], "video": "https://video.twimg.com/q.mp4",
          "video_kind": "video"}


@test
def a_tweet_brings_its_links_and_the_post_it_shares():
    from nodes import fetch_tweets
    tweet = fetch_tweets._parse_entry(_relay_entry(shared=SHARED))
    assert tweet.links[0]["url"] == "https://openai.com/index/codex-review/"
    assert tweet.shared["handle"] == "OpenAIDevs" and tweet.shared["kind"] == "quoted"
    old = fetch_tweets._parse_entry({"data": json.dumps({"tweet_id": "1", "handle": "openai",
                                                       "text": "x", "url": "u", "created_at": ""})})
    assert old.links == () and old.shared is None          # a message from before the change still reads


@test
def a_tweet_is_stored_as_a_labelled_source():
    from nodes import collect_loop, fetch_tweets
    tweet = fetch_tweets._parse_entry(_relay_entry(tweet_id="502", shared=SHARED))
    assert collect_loop._store_tweet(tweet)
    row = db.conn().execute("SELECT * FROM items WHERE external_id = '502'").fetchone()
    body = row["body"]
    assert body.startswith("POST by @openai on X")
    assert "https://openai.com/index/codex-review/" in body and "t.co" not in body
    assert "QUOTED POST by @openaidevs" in body and "Background mode is live" in body
    assert body.index("POST by @openai") < body.index("QUOTED POST")
    links = json.loads(row["links_json"])
    assert [l["url"] for l in links] == ["https://openai.com/index/codex-review/",
                                         "https://platform.openai.com/docs/background"]   # x.com link skipped
    assert row["link_url"] == "https://openai.com/index/codex-review/"
    media = json.loads(row["media_json"])
    assert {"https://pbs.twimg.com/media/own.jpg", "https://pbs.twimg.com/media/q.jpg"} <= set(media["images"])
    assert any(v["url"] == "https://video.twimg.com/q.mp4" for v in media["videos"])

    retweet = dict(SHARED, kind="retweeted")
    tweet = fetch_tweets._parse_entry(_relay_entry(tweet_id="503", text="RT @OpenAIDevs: Background mode…",
                                                   links=[], media=[], shared=retweet))
    assert collect_loop._store_tweet(tweet)
    row = db.conn().execute("SELECT * FROM items WHERE external_id = '503'").fetchone()
    assert row["body"].startswith("@openai REPOSTED this post by @openaidevs")
    assert "RT @" not in row["body"] and row["title"].startswith("Background mode is live")


@test
async def the_pages_a_tweet_links_to_are_read_into_its_source():
    from nodes import article, collect_loop, fetch_tweets
    many = [{"url": f"https://site{i}.dev/page", "short": f"https://t.co/{i}", "title": f"Page {i}",
             "description": ""} for i in range(5)]
    tweet = fetch_tweets._parse_entry(_relay_entry(tweet_id="504", links=many, media=[],
                                                   text="Five new templates for Sora videos"))
    assert collect_loop._store_tweet(tweet)
    item = db.conn().execute("SELECT * FROM items WHERE external_id = '504'").fetchone()
    assert len(json.loads(item["links_json"])) == config.TWEET_MAX_LINKS == 3
    read = []

    async def plain(url):
        read.append(url)
        if "site1" in url:
            return None, ""                         # one page cannot be read
        return f"Full article text of {url}. " * 20, f"<html><img src='https://{url[8:13]}.dev/i.png'></html>"

    async def nothing(url):
        return None, ""

    async def no_reader(url):
        return None
    real = article._plain, article._browser, article._reader
    article._plain, article._browser, article._reader = plain, nothing, no_reader
    try:
        text = await article.fetch_for(item)
    finally:
        article._plain, article._browser, article._reader = real
    assert read == ["https://site0.dev/page", "https://site1.dev/page", "https://site2.dev/page"]
    assert text.startswith("POST by @openai on X")
    assert "LINKED PAGE 1: https://site0.dev/page" in text and "Full article text of https://site0.dev" in text
    assert "LINKED PAGE 2: https://site1.dev/page" in text and "Page 1" in text    # X's preview stands in
    assert text.index("LINKED PAGE 1") < text.index("LINKED PAGE 2") < text.index("LINKED PAGE 3")
    assert db.get_item(item["id"])["article_text"] == text


@test
def the_sorter_reads_a_tweet_once():
    from nodes import sorter
    row = dict(db.conn().execute("SELECT * FROM items WHERE external_id = '504'").fetchone())
    message = sorter.user_message(row)
    text = message.split("Text:", 1)[1]
    assert text.count("Five new templates for Sora videos") == 1, message
    assert "LINKED PAGE 1" in text


@test
def a_bare_website_name_is_not_a_source_link():
    from nodes import collect_loop, fetch_tweets
    links = [{"url": "http://Z.ai", "short": "https://t.co/z", "title": "", "description": ""},
             {"url": "https://mistral.ai/", "short": "https://t.co/m", "title": "", "description": ""},
             {"url": "https://mistral.ai/news/large-4", "short": "https://t.co/n", "title": "", "description": ""}]
    tweet = fetch_tweets._parse_entry(_relay_entry(tweet_id="505", links=links, text="Mistral Large 4 is out"))
    _title, _body, kept = collect_loop.tweet_source(tweet)
    assert [l["url"] for l in kept] == ["https://mistral.ai/news/large-4"], kept


@test
def the_headline_cut_keeps_sentences_that_come_from_the_source():
    from nodes import writer
    item = {"title": "GOOGLE: A new Playground experiment is now available in the US.",
            "body": "Users on paid plans can generate, while everyone can play games available in the gallery."}
    post = ("<b>A new Google Playground experiment is out in the US</b>\n\n"
            "People on paid plans can generate, and everyone can play the games in the gallery.")
    assert writer.lost_by_cut(item, post), "a sentence built from the source must survive"
    padded = "<b>A new Google Playground experiment is out in the US</b>\n\nIt is a great way to explore creativity."
    assert not writer.lost_by_cut(item, padded), "padding the source never said is still cut"


@test
async def a_source_too_thin_to_write_from_is_capped_below_the_bar():
    from nodes import sorter
    from utils import openrouter

    async def fake(**kwargs):
        return {"relevant": True, "topic": "launch", config.SORTER_AXIS: "everyone",
                "importance": 4, "reason": "new feature"}
    thin = {"id": 1, "title": "A new Playground experiment is now available in the US.", "origin": "x",
            "source_name": "testingcatalog", "topic_hint": "launch", "article_text": "",
            "body": "POST by @testingcatalog on X (https://x.com/t/status/1):\nGOOGLE: A new Playground "
                    "experiment is now available in the US. https://x.com/GoogleLabs/status/2/video/1"}
    rich = {**thin, "article_text": thin["body"] + "\n\nLINKED PAGE 1: https://labs.google/x\n" + "It lets you make games. " * 20}
    real = openrouter.chat_json
    openrouter.chat_json = fake
    try:
        assert (await sorter.execute(thin))["importance"] == 3
        assert (await sorter.execute(rich))["importance"] == 4
    finally:
        openrouter.chat_json = real


# ── Never "Try it here" to a tweet ──

@test
def a_post_never_links_to_x():
    from nodes import publisher
    config.SIGNATURE_HTML = ""
    post = '<b>Odyssey-3 builds a world from a prompt</b>\n\nWalk through it.\n\n<a href="LINK">Try it here</a>'
    tweet = "https://x.com/testingcatalog/status/2108246975883751665"
    out = publisher.compose(post, tweet, link_url="")
    assert "x.com" not in out and "Try it here" not in out, out
    assert out.endswith("Walk through it."), out
    out = publisher.compose(post, tweet, link_url="https://twitter.com/odysseyml/status/1")
    assert "twitter.com" not in out and "Try it here" not in out, out
    out = publisher.compose(post, tweet, link_url="https://odyssey.world/experience")
    assert '<a href="https://odyssey.world/experience">Try it here</a>' in out, out
    assert publisher.is_x_link("https://www.x.com/a") and not publisher.is_x_link("https://x.ai/news")


@test
async def the_link_finder_keeps_only_a_real_page_off_x():
    from nodes import link_finder
    from utils import openrouter
    answers = iter(["https://x.com/odysseyml/status/1", "NONE",
                    "Here it is: https://odyssey.world/experience."])

    async def fake(**kwargs):
        assert kwargs["web_search"]
        return next(answers)

    async def loads(url):
        return url, ""
    real = openrouter.chat_text, link_finder._loads
    openrouter.chat_text, link_finder._loads = fake, loads
    item_id = db.insert_item(origin="x", source_name="testingcatalog", external_id="odyssey3",
                             url="https://x.com/testingcatalog/status/2", title="Odyssey-3")
    item = dict(db.get_item(item_id))
    try:
        assert await link_finder.find(item, "<b>Odyssey-3</b>") == ""
        assert await link_finder.find(item, "<b>Odyssey-3</b>") == ""
        assert await link_finder.find(item, "<b>Odyssey-3</b>") == "https://odyssey.world/experience"
    finally:
        openrouter.chat_text, link_finder._loads = real
    assert db.get_item(item_id)["link_url"] == "https://odyssey.world/experience"
    page = ('<a href="https://odyssey.systems/blog">Blog</a> <a href="https://x.com/odysseyml">X</a>'
            '<a href="https://experience.odyssey.systems"><span>Explore</span></a>')
    assert link_finder.demo_link(page, "https://odyssey.systems/introducing-odyssey-3") == \
        "https://experience.odyssey.systems"
    assert link_finder.demo_link('<a href="https://other.com/try">Try it</a>', "https://odyssey.systems/x") == ""

    async def announcement(**kwargs):
        return "https://openai.com/index/introducing-something/"
    openrouter.chat_text, link_finder._loads = announcement, loads
    try:
        assert await link_finder.find(item, "<b>Something</b>") == ""
    finally:
        openrouter.chat_text, link_finder._loads = real



# ── A page's own date catches old news ──

@test
async def an_old_page_is_neither_news_nor_the_link():
    from nodes import article, link_finder
    from pipeline import stations
    from utils import openrouter
    old = '<meta property="article:published_time" content="2026-05-28"/>'
    assert article.page_date(old).strftime("%Y-%m-%d") == "2026-05-28"
    assert article.page_date('{\\"datePublished\\":\\"2026-05-28\\"}').day == 28
    assert article.page_date("<p>no date</p>") is None
    assert article.is_old(article.page_date(old), 48) and not article.is_old(None, 48)

    async def fake(**kwargs):
        return "https://claude.com/blog/introducing-dynamic-workflows-in-claude-code"

    async def loads(url):
        return url, old
    real = openrouter.chat_text, link_finder._loads
    openrouter.chat_text, link_finder._loads = fake, loads
    item_id = db.insert_item(origin="x", source_name="claudedevs", external_id="dynwf",
                             url="https://x.com/ClaudeDevs/status/3", title="Dynamic workflows")
    try:
        assert await link_finder.find(dict(db.get_item(item_id)), "<b>Dynamic workflows</b>") == ""
    finally:
        openrouter.chat_text, link_finder._loads = real

    async def plain(url):
        return "The article text. " * 40, old
    real_plain, article._plain = article._plain, plain
    item_id = db.insert_item(origin="rss", source_name="futuretools", external_id="relisted",
                             url="https://www.anthropic.com/news/relisted", title="Relisted launch")
    try:
        state = await stations.fetch_article_node({"item": dict(db.get_item(item_id))})
    finally:
        article._plain = real_plain
    assert state == {"outcome": "stale"}, state
    assert db.get_item(item_id)["status"] == "skipped_stale"


# ── 2026-10-10: the product, never an article about it; no repeats, no filler ──

@test
def an_aggregator_page_links_the_product_not_an_article():
    from nodes import article, publisher
    page = ('<main><a href="https://blog.cloudflare.com/clef-faster/">source</a>'
            '<a href="https://techcrunch.com/2026/10/09/cloudflare-clef/">news</a>'
            '<a href="https://huggingface.co/Cloudflare/clef-omni">model</a>'
            '<a href="https://developers.cloudflare.com/workers-ai/models/clef-omni">docs</a></main>')
    url = "https://ai-tldr.dev/releases/cloudflare-clef-omni/"
    assert article.product_link(page, url) == "https://developers.cloudflare.com/workers-ai/models/clef-omni"
    only_news = '<main><a href="https://techcrunch.com/2026/10/09/x/">a</a><a href="https://blog.x.ai/y/">b</a></main>'
    assert article.product_link(only_news, url) == ""
    assert article.is_article_url("https://9to5google.com/2026/10/08/gemini-agent/")
    assert not article.is_article_url("https://red.anthropic.com/oss-scanner")
    out = publisher.compose('<b>Clef-omni</b>\n\n<a href="LINK">Try it here</a>', url, "")
    assert "ai-tldr.dev" not in out and "Try it here" not in out, out


def test_rules_are_fixable():
    from nodes import editor
    from pipeline import stations
    for rule in ("REPEATS", "FILLER"):
        assert rule in editor.RULES and rule in stations.FIXABLE_RULES


@test
def repeats_and_filler_send_the_post_back_for_a_rewrite():
    test_rules_are_fixable()
    text = config.WRITER_PROMPT_PATH.read_text()
    assert "Every line says something new" in text and "Who made it" in text

# ── A rewrite edits the rejected draft, with every request so far ──

@test
async def a_rewrite_edits_the_previous_draft_and_keeps_every_request():
    from nodes import writer
    from utils import openrouter
    seen = {}

    async def fake(**kwargs):
        seen["user"] = kwargs["user"]
        return "<b>Post</b>\n\n<a href=\"LINK\">See it here</a>"
    real, openrouter.chat_text = openrouter.chat_text, fake
    item = {"id": 1, "source_name": "openai", "title": "GPT", "body": "text " * 50, "origin": "rss",
            "topic": "launch", "topic_hint": "launch", "article_text": ""}
    try:
        await writer.execute(item, editor_feedback="1. JARGON: explain SDK\n2. FACTUAL_DRIFT: drop 'free'",
                             previous_draft="<b>A free SDK</b>")
    finally:
        openrouter.chat_text = real
    assert "<b>A free SDK</b>" in seen["user"]
    assert "explain SDK" in seen["user"] and "drop 'free'" in seen["user"]
    assert config.MAX_REWRITES >= 3

print(f"{len(PASSED)} passed, {len(FAILED)} failed")
for line in FAILED:
    print("  FAIL", line[:240])
sys.exit(1 if FAILED else 0)
