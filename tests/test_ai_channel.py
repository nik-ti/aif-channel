"""Tests for the AI news channel, with every model call faked.

They check the SPEC.md rules that do not depend on a model's judgement: the AI
prompts are its own, links and the signature are added in code, the sources
parse, and the channel stays out of Market One's tweets.
Run: CHANNEL=ai_news /usr/bin/python3 tests/test_ai_channel.py
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

if config.CHANNEL != "ai_news":
    print("run with CHANNEL=ai_news")
    sys.exit(1)

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
    from brain import graph
    assert "video_analyst" in graph.graph.get_graph().nodes
    assert config.PIPELINE.index("video_analyst") > config.PIPELINE.index("repeat_check")


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
    from brain import nodes
    assert "JARGON" in nodes.FIXABLE_RULES


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
    assert "none" in config.MARKETS

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


@test
def this_channel_stays_out_of_market_ones_tweets():
    assert config.TWEET_STREAM_GROUP != "news-channel"
    from nodes import collect_loop
    assert not collect_loop.reads_tweets()


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
    assert asked == ["https://player.vimeo.com/video/1?h=a"] and saved == (tmp, 1000)


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
    from brain import graph
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
    assert config.PIPELINE.index("fetch_article") < config.PIPELINE.index("sorter")
    from brain import nodes
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
        state = await nodes.fetch_article_node({"item": dict(db.get_item(item_id))})
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
    from brain import nodes
    assert "skill" in config.VALID_TOPICS and config.TOPIC_LIMITS["resource"][0] == 2
    assert config.TOPIC_LIMITS["skill"][0] == 2
    db.conn().execute("DELETE FROM posts"); db.conn().commit()
    assert nodes.topic_limit_reason("skill") == ""
    _sent_post("skill", 30)
    assert "hours" in nodes.topic_limit_reason("skill")            # too soon after the last one
    db.conn().execute("UPDATE posts SET sent_at=datetime('now','-5 hours')"); db.conn().commit()
    assert nodes.topic_limit_reason("skill") == ""                 # spaced enough, 1 of 2 today
    _sent_post("skill", 300)
    assert "2 a day" in nodes.topic_limit_reason("skill")          # the day's two are used
    assert nodes.topic_limit_reason("launch") == ""                # launches are not limited


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
    from brain import nodes
    item_id = _capped("Skill C", "skill", 4, 1)
    _sent_post("skill", 5)                       # the limit would refuse it now
    state = await nodes.sorter_node({"item": dict(db.get_item(item_id)), "released": True})
    assert not state.get("outcome"), state
    assert state["sorter_verdict"]["topic"] == "skill"
    from brain import graph
    assert "released" in graph.BrainState.__annotations__

print(f"{len(PASSED)} passed, {len(FAILED)} failed")
for line in FAILED:
    print("  FAIL", line[:240])
sys.exit(1 if FAILED else 0)
