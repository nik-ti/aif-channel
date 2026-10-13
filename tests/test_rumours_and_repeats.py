"""The 2026-10-13 fixes (SPEC.md): rumours, one product three times, double sends, source talk.

Every model, embedding and Telegram call is faked.
Run: /usr/bin/python3 -m unittest tests/test_rumours_and_repeats.py
"""

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

config.DB_PATH = Path(tempfile.mkdtemp()) / "test.db"

from telegram.error import TimedOut  # noqa: E402

from nodes import dedup, judge, link_finder, publisher, sorter  # noqa: E402
from pipeline import stations  # noqa: E402
from utils import db, embeddings, openrouter, semantic_memory, telegram_client, telegram_error  # noqa: E402

db.init_db()


def _item(title: str, *, status: str = "queued", url: str = "", body: str = "") -> int:
    n = db.conn().execute("SELECT COUNT(*) FROM items").fetchone()[0]
    return db.insert_item(origin="rss", source_name="futuretools", external_id=f"r{n}",
                          url=url or f"https://e.x/{n}", title=title,
                          body=body or f"{title}. " * 20, status=status,
                          norm_title=title.lower())


class Rumours(unittest.IsolatedAsyncioTestCase):
    """A sighting or a guess is not news, whatever score the model gives it."""

    async def judge(self, title, quote, body=""):
        item = {"id": 1, "origin": "x", "source_name": "testingcatalog", "topic": "feature",
                "company": "Google", "title": title, "body": body or f"{title}\n{quote} " * 6}
        answer = {"relevant": True, "basis": "news", "evidence": quote,
                  config.SORTER_AXIS: "everyone", "importance": 4, "reason": "a new feature"}
        with patch.object(openrouter, "chat_json", new_callable=AsyncMock, return_value=answer):
            return await sorter.execute(item)

    async def test_a_hedged_headline_is_not_news(self):
        title = "Google seems to be rolling out support for custom MCPs on Gemini desktop app."
        result = await self.judge(title, title)
        self.assertFalse(result["relevant"], result)
        self.assertIn("unconfirmed", result["reason"])

    async def test_a_sighting_is_not_news_even_with_a_plain_quote(self):
        quote = "Fable 5.5 appeared in Azure's East US 2 model catalog with GenerallyAvailable status"
        result = await self.judge("ANTHROPIC: Claude Fable 5.5 traces have been spotted in Azure configs.",
                                  quote)
        self.assertFalse(result["relevant"], result)

    async def test_a_confirmed_rollout_still_passes(self):
        quote = "Gemini 4 Argon is now available in the Gemini app for Pro and Ultra subscribers."
        result = await self.judge("Google launches Gemini 4 Argon", quote)
        self.assertTrue(result["relevant"], result)


class DedupLooksPastARejectedMatch(unittest.IsolatedAsyncioTestCase):
    """Argon: the first "same event" match was a rejected item, so a covered one was never checked."""

    async def test_a_published_match_behind_a_rejected_one_still_counts(self):
        rejected = _item("Gemini 4 Argon is now globally available.", status="low_impact")
        published = _item("Google officially announces Gemini 4 Argon", status="published")
        new = _item("Gemini 4 Argon: Built to solve your hardest problems")
        item = dict(db.get_item(new))
        with patch.object(embeddings, "embed_one", new_callable=AsyncMock, return_value=[1.0]), \
             patch.object(embeddings, "to_blob", return_value=b"x"), \
             patch.object(db, "recent_embeddings", return_value=[(rejected, b""), (published, b"")]), \
             patch.object(embeddings, "most_similar", return_value=[(rejected, 0.85), (published, 0.8)]), \
             patch.object(judge, "execute_three_way", new_callable=AsyncMock,
                          return_value=("same_event", "same launch")):
            verdict, matched, _ = await dedup.check_meaning(item, persist=False)
        self.assertEqual((verdict, matched), ("duplicate", published))

    async def test_only_rejected_matches_let_the_item_through(self):
        rejected = _item("Gemini 4 Argon arrives today", status="irrelevant")
        item = dict(db.get_item(_item("Gemini 4 Argon is here")))
        with patch.object(embeddings, "embed_one", new_callable=AsyncMock, return_value=[1.0]), \
             patch.object(embeddings, "to_blob", return_value=b"x"), \
             patch.object(db, "recent_embeddings", return_value=[(rejected, b"")]), \
             patch.object(embeddings, "most_similar", return_value=[(rejected, 0.85)]), \
             patch.object(judge, "execute_three_way", new_callable=AsyncMock,
                          return_value=("same_event", "same launch")):
            verdict, _, _ = await dedup.check_meaning(item, persist=False)
        self.assertEqual(verdict, "different")


class OneProductOncePerCooldown(unittest.IsolatedAsyncioTestCase):
    """Three Argon posts in 31 minutes: a follow-up waits out FOLLOW_UP_COOLDOWN_HOURS."""

    def matches(self, minutes_ago: int):
        sent = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")
        return [{"id": 88, "text": "<b>Gemini 4 Argon has started rolling out</b>",
                 "sent_at": sent, "score": 0.8}]

    async def sift(self, state, matches):
        async def fake(text, *, now=None, persist=True):
            return matches
        sifter_answer = {"new_facts": [], "worth_a_post": True, "reason": "r"}
        with patch.object(semantic_memory, "published_matches", fake), \
             patch.object(openrouter, "chat_json", new_callable=AsyncMock,
                          return_value=sifter_answer) as model:
            return await stations.sifter_node(state), model

    async def test_a_follow_up_minutes_later_is_held_without_asking_the_sifter(self):
        item_id = _item("Gemini 4 Argon: Built to solve your hardest problems")
        state, model = await self.sift({"item": dict(db.get_item(item_id))}, self.matches(28))
        self.assertEqual(state.get("outcome"), "nothing_new", state)
        model.assert_not_awaited()
        row = db.get_item(item_id)
        self.assertEqual(row["status"], "held")
        self.assertIn("already posted about this", row["status_reason"])

    async def test_after_the_cooldown_the_sifter_decides(self):
        item_id = _item("Gemini 4 Argon now in Search")
        hours = config.FOLLOW_UP_COOLDOWN_HOURS * 60 + 30
        _, model = await self.sift({"item": dict(db.get_item(item_id))}, self.matches(hours))
        model.assert_awaited_once()

    async def test_a_forced_item_ignores_the_cooldown(self):
        item_id = _item("Gemini 4 Argon pricing")
        state, _ = await self.sift({"item": dict(db.get_item(item_id)), "forced": True},
                                   self.matches(5))
        self.assertFalse(state.get("outcome"), state)


class ATimeoutIsNotAFailedSend(unittest.IsolatedAsyncioTestCase):
    """Facebook, 2026-10-13: the clip timed out on our side, arrived anyway, and the text went too."""

    async def test_a_timed_out_clip_is_not_sent_again_as_a_picture_or_text(self):
        item_id = _item("Facebook Launches AI Tools Letting Users Customize Feed")
        post_id = db.create_post(item_id=item_id, topic="feature", post_html="<b>Facebook</b>",
                                 image_url="", writer_model="m")
        db.set_post_media(post_id, media_video_url="https://e.x/v.mp4", media_video_kind="mp4",
                          media_image_url="https://e.x/i.jpg")
        with patch.object(telegram_client, "send_clip", new_callable=AsyncMock,
                          side_effect=TimedOut()), \
             patch.object(telegram_client, "send_photo", new_callable=AsyncMock) as photo, \
             patch.object(telegram_client, "send_text", new_callable=AsyncMock) as text, \
             patch.object(telegram_error, "send_error") as alert:
            sent = await publisher.execute(dict(db.get_item(item_id)), "<b>Facebook</b>", post_id)
        self.assertTrue(sent)
        photo.assert_not_awaited()
        text.assert_not_awaited()
        alert.assert_called_once()
        self.assertEqual(db.get_item(item_id)["status"], "published")
        self.assertIn("timed out", db.get_item(item_id)["status_reason"])

    async def test_a_refused_clip_still_falls_back_to_the_picture(self):
        from telegram.error import BadRequest
        item_id = _item("Some launch with a huge video")
        post_id = db.create_post(item_id=item_id, topic="feature", post_html="<b>X</b>",
                                 image_url="", writer_model="m")
        db.set_post_media(post_id, media_video_url="https://e.x/v.mp4", media_video_kind="mp4",
                          media_image_url="https://e.x/i.jpg")
        with patch.object(telegram_client, "send_clip", new_callable=AsyncMock,
                          side_effect=BadRequest("file is too big")), \
             patch.object(telegram_client, "send_photo", new_callable=AsyncMock,
                          return_value=7) as photo:
            sent = await publisher.execute(dict(db.get_item(item_id)), "<b>X</b>", post_id)
        self.assertTrue(sent)
        photo.assert_awaited_once()


class ALinkToTheThingItself(unittest.IsolatedAsyncioTestCase):
    """Fireship's Adobe clones went out with no link though the repos were one search away."""

    async def test_an_aggregator_item_without_a_product_link_gets_a_search(self):
        item_id = _item("Fireship — Every app on Earth is now open source",
                        url="https://ai-tldr.dev/releases/fireship-every-app-open-source-oct12/")
        state = {"item": dict(db.get_item(item_id)), "post_html": "<b>x</b>", "post_id": 1}
        with patch.object(link_finder, "find", new_callable=AsyncMock,
                          return_value="https://github.com/storytold/filmcraft") as find, \
             patch.object(publisher, "execute", new_callable=AsyncMock, return_value=True) as send:
            await stations.publish_node(state)
        find.assert_awaited_once()
        self.assertEqual(send.await_args.args[0]["link_url"], "https://github.com/storytold/filmcraft")

    async def test_an_ordinary_article_is_not_searched(self):
        item_id = _item("Facebook Launches AI Tools", url="https://about.fb.com/news/2026/10/x/")
        state = {"item": dict(db.get_item(item_id)), "post_html": "<b>x</b>", "post_id": 1}
        with patch.object(link_finder, "find", new_callable=AsyncMock) as find, \
             patch.object(publisher, "execute", new_callable=AsyncMock, return_value=True):
            await stations.publish_node(state)
        find.assert_not_awaited()

    def test_the_link_finder_takes_an_open_source_projects_code_page(self):
        self.assertIn("GitHub", link_finder.PROMPT)

    async def find(self, answers, results, pages=None):
        """link_finder.find with each search answering from `answers` and returning `results`."""
        replies, asked = iter(answers), []

        async def search(**kwargs):
            asked.append(kwargs["user"])
            return next(replies), results.pop(0)

        async def loads(url):
            return url, (pages or {}).get(url, "")
        item_id = _item("Fireship — Every app on Earth is now open source",
                        url="https://ai-tldr.dev/releases/fireship-every-app-open-source-oct12/")
        with patch.object(openrouter, "web_search", search), patch.object(link_finder, "_loads", loads):
            return await link_finder.find(dict(db.get_item(item_id)), "<b>Seven Adobe apps</b>"), asked

    async def test_news_in_the_results_leads_to_a_second_search_on_the_name(self):
        news = "https://devops.com/open-source-final-has-its-take-on-the-adobe-creative-suite"
        found, asked = await self.find(
            [f"NAME: ArtCraft\nURL: {news}", "https://getartcraft.app/"],
            [[news], ["https://github.com/storytold/artcraft", "https://getartcraft.app/"]])
        self.assertEqual(found, "https://getartcraft.app/")
        self.assertEqual(len(asked), 2)
        self.assertIn("ArtCraft", asked[1])

    async def test_an_address_the_search_never_returned_is_refused(self):
        found, _ = await self.find(
            ["NAME: ArtCraft\nURL: NONE", "https://github.com/ArtCraft-Studio"],
            [["https://xda-developers.com/x"], ["https://github.com/storytold/artcraft"]])
        self.assertEqual(found, "")

    async def test_a_referral_code_is_dropped_and_a_home_page_is_not_left_for_its_app(self):
        home = '<a href="https://app.getartcraft.com/create-image">Launch App</a>'
        found, _ = await self.find(
            ["NAME: ArtCraft\nURL: https://getartcraft.com/?r=rbohan9388"],
            [["https://getartcraft.com/?r=rbohan9388"]], pages={"https://getartcraft.com/": home})
        self.assertEqual(found, "https://getartcraft.com/")

    async def test_an_old_date_on_a_product_page_does_not_matter(self):
        dated = '<meta property="article:published_time" content="2026-06-25"/>'
        found, _ = await self.find(
            ["NAME: Atomic Agent Desktop\nURL: https://atomicagent.io/download/"],
            [["https://atomicagent.io/download/"]], pages={"https://atomicagent.io/download/": dated})
        self.assertEqual(found, "https://atomicagent.io/download/")

    async def test_an_announcement_gives_its_try_link(self):
        page = '<a href="https://experience.odyssey.systems"><span>Explore</span></a>'
        url = "https://odyssey.systems/introducing-odyssey-3"
        found, _ = await self.find([f"NAME: Odyssey-3\nURL: {url}"], [[url]], pages={url: page})
        self.assertEqual(found, "https://experience.odyssey.systems")

    def test_a_headline_address_is_an_article(self):
        from nodes import article
        self.assertTrue(article.is_article_url(
            "https://devops.com/open-source-final-has-its-take-on-the-adobe-creative-suite"))
        self.assertFalse(article.is_article_url("https://getartcraft.com/apps"))
        self.assertFalse(article.is_article_url("https://github.com/someone/a-very-long-repo-name-here"))


class TheSourceIsNotTheStory(unittest.TestCase):
    """"The video claims...", "A user report says...": the post tells the news, not where it read it."""

    def test_the_editor_can_send_back_source_talk(self):
        self.assertIn("SOURCE_TALK", config.EXTRA_EDITOR_RULES)
        self.assertIn("SOURCE_TALK", stations.FIXABLE_RULES)
        self.assertIn("SOURCE_TALK", config.EDITOR_PROMPT_PATH.read_text())

    def test_the_writer_is_told(self):
        self.assertIn("the video", config.WRITER_PROMPT_PATH.read_text())


if __name__ == "__main__":
    unittest.main()
