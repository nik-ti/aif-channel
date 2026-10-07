"""Tests for the image and video analysts, with every model call and download faked.

They check the rules in SPEC.md that do not depend on a model's judgement: what
counts as a candidate, what happens on failure, what the publisher is allowed to
send. Run: /usr/bin/python3 tests/test_media.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

config.DB_PATH = Path(tempfile.mkdtemp()) / "test.db"

from utils import db, telegram_client  # noqa: E402

db.init_db()
try:
    from nodes import image_analyst, media, publisher, video_analyst  # noqa: E402
except ImportError as missing:
    print(f"0 passed — the analysts do not exist yet ({missing})")
    sys.exit(1)

REAL_DOWNLOAD = video_analyst._download     # later tests replace it with fakes
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


def new_item(**fields) -> dict:
    """A queued item row, returned as a dict."""
    n = len(db.conn().execute("SELECT id FROM items").fetchall())
    item_id = db.insert_item(origin="x", source_name="test", external_id=f"t{n}",
                             url=f"https://x.com/t/{n}", title=f"title {n}",
                             body="body", **fields)
    return dict(db.conn().execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone())


def new_post(item: dict) -> int:
    return db.create_post(item_id=item["id"], topic="tool", post_html="<b>Post</b>",
                          image_url="", writer_model="test")


def fake_images(verdicts: dict[str, str], best: str | None):
    """Replace the image download and the model with fixed answers."""
    async def fetch(url):
        return b"img" if url in verdicts else None

    async def judge(post_text, images):
        rows = [{"index": i + 1, "verdict": verdicts[url], "reason": "test"}
                for i, (url, _) in enumerate(images)]
        index = next((i + 1 for i, (url, _) in enumerate(images) if url == best), 0)
        return {"images": rows, "best": index}

    image_analyst._fetch_image = fetch
    image_analyst._judge = judge


# --- candidates -------------------------------------------------------------

@test
def every_tweet_image_is_a_candidate():
    item = new_item(image_url="https://a/1.jpg")
    db.add_item_media(item["id"], images=["https://a/1.jpg", "https://a/2.jpg", "https://a/3.jpg"])
    item = dict(db.conn().execute("SELECT * FROM items WHERE id=?", (item["id"],)).fetchone())
    assert media.candidates(item).images == ["https://a/1.jpg", "https://a/2.jpg", "https://a/3.jpg"]


@test
def old_rows_without_media_json_still_offer_their_image_and_video():
    item = new_item(image_url="https://a/thumb.jpg", video_url="https://v/1.mp4", video_kind="video")
    found = media.candidates(item)
    assert found.images == ["https://a/thumb.jpg"]
    assert found.videos == [{"url": "https://v/1.mp4", "kind": "video"}]


@test
def a_folded_story_offers_media_from_every_item():
    one = new_item(image_url="https://a/one.jpg")
    two = new_item(image_url="https://a/two.jpg")
    folded = {"id": two["id"], "candidate_media": media.merge([one, two])}
    assert set(media.candidates(folded).images) == {"https://a/one.jpg", "https://a/two.jpg"}


@test
def article_html_gives_og_image_and_drops_icons_and_pixels():
    html = """<html><head><meta property="og:image" content="/hero.png"></head><body>
      <article><p>text</p><img src="https://cdn.site/chart.png" width="900" height="500">
      <img src="https://cdn.site/avatar.png" width="40" height="40">
      <img src="https://track.site/pixel.gif" width="1" height="1">
      <img src="data:image/gif;base64,AAAA">
      <video src="https://cdn.site/demo.mp4"></video></article></body></html>"""
    images, videos = media.from_article_html(html, "https://site.com/post")
    assert images[0] == "https://site.com/hero.png"
    assert "https://cdn.site/chart.png" in images
    assert not any("avatar" in u or "pixel" in u or u.startswith("data:") for u in images)
    assert videos == [{"url": "https://cdn.site/demo.mp4", "kind": "video"}]


@test
def at_most_six_images_reach_the_analyst():
    urls = [f"https://a/{n}.jpg" for n in range(10)]
    seen = []

    async def judge(post_text, images):
        seen.append(len(images))
        return {"images": [], "best": 0}

    async def fetch(url):
        return b"img"
    image_analyst._fetch_image, image_analyst._judge = fetch, judge
    asyncio.run(image_analyst.choose("post", urls))
    assert seen == [6]


# --- the image analyst --------------------------------------------------------

@test
async def best_accepted_image_is_chosen():
    fake_images({"https://a/p.jpg": "reject", "https://a/c.jpg": "accept"}, best="https://a/c.jpg")
    choice = await image_analyst.choose("post", ["https://a/p.jpg", "https://a/c.jpg"])
    assert choice.url == "https://a/c.jpg"


@test
async def none_relevant_is_normal_not_an_error():
    sent = []
    from utils import telegram_error
    original = telegram_error.send_error
    telegram_error.send_error = lambda *a, **k: sent.append(a)
    before = db.counters_today("media_").get("media_error", 0)
    fake_images({"https://a/p.jpg": "reject", "https://a/l.jpg": "reject"}, best=None)
    choice = await image_analyst.choose("post", ["https://a/p.jpg", "https://a/l.jpg"])
    telegram_error.send_error = original
    assert choice.url == "" and choice.failed is False
    assert sent == []
    assert db.counters_today("media_").get("media_error", 0) == before


@test
async def a_best_index_the_model_rejected_is_not_used():
    fake_images({"https://a/p.jpg": "reject"}, best="https://a/p.jpg")
    choice = await image_analyst.choose("post", ["https://a/p.jpg"])
    assert choice.url == ""


@test
async def model_failure_means_no_image():
    async def broken(post_text, images):
        raise RuntimeError("timeout")
    async def fetch(url):
        return b"img"
    image_analyst._fetch_image, image_analyst._judge = fetch, broken
    choice = await image_analyst.choose("post", ["https://a/c.jpg"])
    assert choice.url == "" and choice.failed is True


@test
async def an_out_of_range_index_means_no_image():
    async def judge(post_text, images):
        return {"images": [{"index": 9, "verdict": "accept", "reason": "x"}], "best": 9}
    async def fetch(url):
        return b"img"
    image_analyst._fetch_image, image_analyst._judge = fetch, judge
    assert (await image_analyst.choose("post", ["https://a/c.jpg"])).url == ""


@test
async def images_that_cannot_be_downloaded_are_never_judged_or_sent():
    fake_images({"https://a/ok.jpg": "accept"}, best="https://a/ok.jpg")
    choice = await image_analyst.choose("post", ["https://a/gone.jpg", "https://a/ok.jpg"])
    assert choice.url == "https://a/ok.jpg"


# --- the video analyst --------------------------------------------------------

def fake_video(duration: float, size_mb: float, verdict: str = "accept"):
    calls = []

    async def download(url):
        if size_mb > 20:
            return None
        path = Path(tempfile.mkstemp(suffix=".mp4")[1])
        return path, int(size_mb * 1_000_000), url["url"] if isinstance(url, dict) else url

    async def judge(post_text, path, kind):
        calls.append(path)
        return {"verdict": verdict, "reason": "test"}

    video_analyst._download = download
    video_analyst._duration = lambda path: duration
    video_analyst._judge = judge
    return calls


@test
async def a_video_over_two_minutes_never_reaches_the_model():
    calls = fake_video(duration=150, size_mb=5)
    choice = await video_analyst.choose("post", [{"url": "https://v/long.mp4", "kind": "video"}])
    assert choice.url == "" and calls == []


@test
async def a_video_over_20mb_never_reaches_the_model():
    calls = fake_video(duration=30, size_mb=25)
    choice = await video_analyst.choose("post", [{"url": "https://v/big.mp4", "kind": "video"}])
    assert choice.url == "" and calls == []


@test
async def a_matching_short_video_is_chosen():
    fake_video(duration=30, size_mb=5, verdict="accept")
    choice = await video_analyst.choose("post", [{"url": "https://v/ok.mp4", "kind": "gif"}])
    assert choice.url == "https://v/ok.mp4" and choice.kind == "gif"


@test
async def video_model_failure_means_no_video():
    fake_video(duration=30, size_mb=5)

    async def broken(post_text, path, kind):
        raise RuntimeError("down")
    video_analyst._judge = broken
    choice = await video_analyst.choose("post", [{"url": "https://v/ok.mp4", "kind": "video"}])
    assert choice.url == "" and choice.failed is True


# --- the stations and the publisher -------------------------------------------

def sends():
    """Capture what the publisher hands Telegram."""
    log = []

    def make(kind):
        async def send(*args, reply_to_message_id=None, **kwargs):
            log.append((kind, args[0] if kind != "text" else ""))
            return 1000 + len(log)
        return send
    telegram_client.send_text = make("text")
    telegram_client.send_photo = make("photo")
    telegram_client.send_clip = make("clip")
    return log


async def run_stations(item: dict, post_id: int, check_videos: bool):
    from pipeline import stations
    config.CHECK_VIDEOS = check_videos
    state = {"item": item, "post_id": post_id, "post_html": "<b>Post</b>"}
    await stations.image_analyst_node(state)
    if check_videos:
        await stations.video_analyst_node(state)


@test
async def with_video_checks_off_clips_go_out_unchecked():
    item = new_item(image_url="https://a/thumb.jpg", video_url="https://v/m.mp4", video_kind="video")
    post_id = new_post(item)
    calls = fake_video(duration=30, size_mb=5, verdict="reject")
    fake_images({"https://a/thumb.jpg": "reject"}, best=None)
    await run_stations(item, post_id, check_videos=False)
    log = sends()
    assert await publisher.execute(item, "<b>Post</b>", post_id)
    assert log == [("clip", "https://v/m.mp4")] and calls == []


@test
async def the_publisher_never_sends_an_unjudged_image():
    item = new_item(image_url="https://a/never-judged.jpg")
    post_id = new_post(item)          # no station ran
    log = sends()
    assert await publisher.execute(item, "<b>Post</b>", post_id)
    assert log == [("text", "")]


@test
async def a_rejected_image_is_not_sent():
    item = new_item(image_url="https://a/person.jpg")
    post_id = new_post(item)
    fake_images({"https://a/person.jpg": "reject"}, best=None)
    await run_stations(item, post_id, check_videos=False)
    log = sends()
    assert await publisher.execute(item, "<b>Post</b>", post_id)
    assert log == [("text", "")]
    assert "person" not in (db.get_post_media(post_id)["media_image_url"] or "")
    assert db.get_post_media(post_id)["media_note"]          # the reason is recorded


@test
async def ai_channel_video_wins_and_the_image_is_the_fallback():
    item = new_item(image_url="https://a/chart.jpg", video_url="https://v/demo.mp4", video_kind="video")
    post_id = new_post(item)
    fake_images({"https://a/chart.jpg": "accept"}, best="https://a/chart.jpg")
    fake_video(duration=30, size_mb=5, verdict="accept")
    await run_stations(item, post_id, check_videos=True)
    chosen = db.get_post_media(post_id)
    assert chosen["media_video_url"] == "https://v/demo.mp4"
    assert chosen["media_image_url"] == "https://a/chart.jpg"
    log = sends()
    assert await publisher.execute(item, "<b>Post</b>", post_id)
    assert log == [("clip", "https://v/demo.mp4")]


@test
async def ai_channel_rejected_video_is_not_sent():
    item = new_item(video_url="https://v/other.mp4", video_kind="video")
    post_id = new_post(item)
    fake_images({}, best=None)
    fake_video(duration=30, size_mb=5, verdict="reject")
    await run_stations(item, post_id, check_videos=True)
    log = sends()
    assert await publisher.execute(item, "<b>Post</b>", post_id)
    assert log == [("text", "")]


@test
async def a_station_failure_still_sends_the_text():
    item = new_item(image_url="https://a/c.jpg")
    post_id = new_post(item)

    async def broken(*a, **k):
        raise RuntimeError("boom")
    image_analyst.choose_original = image_analyst.choose
    image_analyst.choose = broken
    try:
        await run_stations(item, post_id, check_videos=False)
    finally:
        image_analyst.choose = image_analyst.choose_original
    log = sends()
    assert await publisher.execute(item, "<b>Post</b>", post_id)
    assert log == [("text", "")]


# --- Telegram cannot fetch the address ----------------------------------------

class FakeBot:
    """Refuses media given as an address, like Telegram did for post 663; takes bytes."""
    def __init__(self):
        self.calls = []

    async def _media(self, method, value, **kwargs):
        from telegram.error import BadRequest
        self.calls.append((method, type(value).__name__))
        if isinstance(value, str):
            raise BadRequest("Failed to get http url content")
        return type("Message", (), {"message_id": 77})()

    async def send_photo(self, *, photo, **kwargs):
        return await self._media("send_photo", photo, **kwargs)

    async def send_video(self, *, video, **kwargs):
        return await self._media("send_video", video, **kwargs)


def with_fake_bot():
    import importlib
    from utils import telegram_client as real
    real = importlib.reload(real)
    bot = FakeBot()

    async def get_bot():
        return bot

    async def download(url, limit_mb):
        return b"\xff\xd8 jpeg bytes"
    real._get_bot, real._download = get_bot, download
    return real, bot


@test
async def an_image_telegram_cannot_fetch_is_uploaded_as_a_photo():
    client, bot = with_fake_bot()
    assert await client.send_photo("https://pbs.twimg.com/media/x.jpg", "<b>Post</b>",
                                   reply_to_message_id=553) == 77
    assert bot.calls == [("send_photo", "str"), ("send_photo", "bytes")]


@test
async def a_clip_telegram_cannot_fetch_is_uploaded_as_a_video():
    client, bot = with_fake_bot()
    assert await client.send_clip("https://video.twimg.com/v.mp4", "video", "<b>Post</b>") == 77
    assert bot.calls == [("send_video", "str"), ("send_video", "bytes")]


@test
async def a_clip_too_big_for_telegram_falls_back_to_a_smaller_version():
    tried = []

    async def save(url):
        tried.append(url)
        if "1080" in url:
            raise ValueError(f"over {config.MAX_VIDEO_MB} MB")
        path = Path(tempfile.mkstemp(suffix=".mp4")[1])
        return path, 9_000_000
    real_save = video_analyst._save
    video_analyst._save = save
    try:
        video = {"url": "https://v/1080.mp4", "kind": "video",
                 "variants": ["https://v/1080.mp4", "https://v/720.mp4", "https://v/480.mp4"]}
        path, size, used = await REAL_DOWNLOAD(video)
        path.unlink(missing_ok=True)
    finally:
        video_analyst._save = real_save
    assert used == "https://v/720.mp4" and tried == ["https://v/1080.mp4", "https://v/720.mp4"]


print(f"{len(PASSED)} passed, {len(FAILED)} failed")
for line in FAILED:
    print("  FAIL", line[:200])
sys.exit(1 if FAILED else 0)
