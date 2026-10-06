"""Reader-memory contract checks. Temporary databases and fake APIs only."""

import asyncio
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from brain import nodes as brain_nodes
from nodes import echo, stories, publish_loop
from utils import db, embeddings

NOW = datetime(2026, 10, 5, 12, 52, tzinfo=timezone.utc)
OLD = "US Treasury yields update: 30-year yield reached 5.5185%, a fresh 22-year high."
NEW = "US 30-year Treasury yield rises to 5.656%"
ROUNDUP = ("US Treasury yields update\n\nThe 30-year yield crossed 5.7% for the first time since 2002, "
           "while the 10-year yield reached a fresh 24-year high of 5.3493%.")


def novelty(kind, quote, previous_quote="", threshold="", current_value="", previous_value=""):
    return {"kind": kind, "quote": quote, "previous_quote": previous_quote,
            "threshold": threshold, "current_value": current_value, "previous_value": previous_value}


def stamp(at):
    return at.strftime("%Y-%m-%d %H:%M:%S")


class ReaderMemory(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.old_path, self.old_conn = config.DB_PATH, db._conn
        config.DB_PATH = Path(self.directory.name) / "memory.db"
        db._conn = None
        db.init_db()
        self.number = 0

    def tearDown(self):
        if db._conn:
            db._conn.close()
        config.DB_PATH, db._conn = self.old_path, self.old_conn
        self.directory.cleanup()

    def item(self, title=NEW, at=NOW):
        self.number += 1
        ident = db.insert_item(origin="x", source_name="test", external_id=str(self.number),
                               url="https://example.com", title=title, body=title)
        db.conn().execute("UPDATE items SET fetched_at=? WHERE id=?", (stamp(at), ident))
        db.conn().commit()
        return dict(db.get_item(ident))

    def post(self, text=OLD, at=NOW-timedelta(days=10), status="sent", story_id=None):
        item = self.item(text, at)
        if story_id:
            db.attach_item_to_story(item["id"], story_id)
        ident = db.create_post(item_id=item["id"], topic="markets", post_html=text,
                               image_url="", writer_model="test")
        db.conn().execute("UPDATE posts SET status=?,sent_at=?,telegram_message_id=? WHERE id=?",
                          (status, stamp(at), ident, ident))
        db.conn().commit()
        return ident

    @staticmethod
    async def vectors(texts):
        return [[1.0, 0.0] if "Treasury" in text or "yield" in text else [0.0, 1.0]
                for text in texts]

    async def test_all_in_window_posts_are_searched_and_cached_across_restart(self):
        from utils import semantic_memory as memory
        old = self.post()
        for n in range(55):
            self.post(f"Unrelated news {n}", NOW-timedelta(hours=n+1))
        self.post("Treasury obsolete", NOW-timedelta(days=61))
        self.post("Treasury rejected", status="declined")
        self.post("Treasury deleted", status="deleted")
        with patch.object(embeddings, "embed", side_effect=self.vectors) as embed:
            matches = await memory.published_matches(NEW, now=NOW)
            self.assertEqual([r["id"] for r in matches], [old])
            first_count = sum(len(call.args[0]) for call in embed.call_args_list)
            self.assertEqual(first_count, 57)  # 56 sent posts plus the input
            db.conn().close()
            db._conn = None
            embed.reset_mock()
            self.assertEqual((await memory.published_matches(NEW, now=NOW))[0]["id"], old)
            self.assertEqual(sum(len(call.args[0]) for call in embed.call_args_list), 1)

    async def test_cache_invalidates_changed_text_and_same_size_model(self):
        from utils import semantic_memory as memory
        ident = self.post()
        with patch.object(embeddings, "embed", side_effect=self.vectors) as embed:
            await memory.published_matches(NEW, now=NOW)
            db.update_post_text(ident, OLD+" Updated.")
            db.set_post_status(ident, "sent")
            embed.reset_mock()
            await memory.published_matches(NEW, now=NOW)
            self.assertEqual(sum(len(c.args[0]) for c in embed.call_args_list), 2)
            with patch.object(config, "EMBEDDING_MODEL", "different-model-same-dimensions"):
                embed.reset_mock()
                await memory.published_matches(NEW, now=NOW)
                self.assertEqual(sum(len(c.args[0]) for c in embed.call_args_list), 2)

    async def test_retention_uses_publication_age_and_preserves_history(self):
        from utils import semantic_memory as memory
        ident = self.post(at=NOW-timedelta(days=59))
        with patch.object(embeddings, "embed", side_effect=self.vectors):
            await memory.published_matches(NEW, now=NOW)
        self.assertEqual(db.conn().execute("SELECT count(*) FROM memory_embeddings").fetchone()[0], 1)
        db.prune_memory_embeddings(now=NOW+timedelta(days=2))
        self.assertEqual(db.conn().execute("SELECT count(*) FROM memory_embeddings").fetchone()[0], 0)
        self.assertEqual(db.conn().execute("SELECT status FROM posts WHERE id=?", (ident,)).fetchone()[0], "sent")
        self.assertEqual(db.conn().execute("SELECT count(*) FROM items").fetchone()[0], 1)

    async def test_read_only_retrieval_does_not_populate_cache(self):
        from utils import semantic_memory as memory
        self.post()
        with patch.object(embeddings, "embed", side_effect=self.vectors):
            self.assertTrue(await memory.published_matches(NEW, now=NOW, persist=False))
        self.assertEqual(db.conn().execute("SELECT count(*) FROM memory_embeddings").fetchone()[0], 0)

    async def test_invalid_or_incomplete_vectors_defer_instead_of_clearing_history(self):
        from utils import semantic_memory as memory
        self.post()
        for vectors in (None, [], [[float("nan"), 0]], [[0, 0]], [[1, 0], [1, 0, 0]]):
            with self.subTest(vectors=vectors), patch.object(embeddings, "embed", return_value=vectors):
                with self.assertRaises(memory.Unavailable):
                    await memory.published_matches(NEW, now=NOW)

    async def test_all_related_posts_reach_collective_judge(self):
        from utils import semantic_memory as memory
        candidates = [{"id": n, "text": f"Treasury evidence {n}", "sent_at": stamp(NOW),
                       "score": 0.8, "story_id": None} for n in range(5)]
        with patch.object(memory, "published_matches", return_value=candidates), \
             patch.object(echo.openrouter, "chat_json", return_value={"verdict": "hold", "reason": "same climb",
                                                                       "covered_claims": [NEW], "new_claims": []}) as judge:
            repeat, why = await echo.repeats_something_published(NEW)
        self.assertTrue(repeat)
        for row in candidates:
            self.assertIn(row["text"], judge.call_args.kwargs["user"])
        self.assertIn("same climb", why)

    async def test_overflow_candidates_are_all_read_before_combined_decision(self):
        from utils import semantic_memory as memory
        candidates = [{"id": n, "text": f"Evidence {n} " + "x"*350, "sent_at": stamp(NOW),
                       "score": 0.8, "story_id": None} for n in range(8)]
        async def verdict(**kw):
            return {"verdict": "hold" if kw["schema_name"] == "combined_coverage" else "send",
                    "reason": "facts known across posts", "covered_claims": ["US", "Treasury"],
                    "new_claims": [] if kw["schema_name"] == "combined_coverage" else [
                        novelty("decision", "US Treasury applies a new auction policy.")]}
        with patch.object(memory, "published_matches", return_value=candidates), \
             patch.object(config, "ECHO_BATCH_CHARS", 1000, create=True), \
             patch.object(echo.openrouter, "chat_json", side_effect=verdict) as judge:
            repeated, _ = await echo.repeats_something_published("US Treasury applies a new auction policy.")
        self.assertTrue(repeated)
        prompts = "\n".join(c.kwargs["user"] for c in judge.call_args_list)
        for row in candidates:
            self.assertIn(row["text"], prompts)
        self.assertGreater(judge.call_count, 2)
        self.assertEqual(judge.call_args.kwargs["schema_name"], "combined_coverage")

    async def test_unavailable_exit_defers_graph_and_approved_retry(self):
        from utils import semantic_memory as memory
        item = self.item()
        post = db.create_post(item_id=item["id"], topic="markets", post_html=NEW,
                              image_url="", writer_model="test")
        db.set_post_status(post, "approved")
        with patch.object(echo, "repeats_something_published", side_effect=memory.Unavailable("offline")), \
             patch.object(publish_loop.publisher, "execute") as send:
            state = await brain_nodes.repeat_check_node({"item": item, "post_id": post, "post_html": NEW})
            self.assertEqual(state["outcome"], "retry")
            self.assertEqual(await publish_loop.process_item(dict(db.get_item(item["id"]))), "retry")
            send.assert_not_called()

    async def test_closed_story_is_offered_and_reopens_with_its_history(self):
        older = NOW-timedelta(days=10)
        seed = self.item(OLD, older)
        sid = db.create_story(headline="US Treasury yields", summary=OLD, item_id=seed["id"], at=stamp(older))
        self.post(OLD, older, story_id=sid)
        db.conn().execute("UPDATE stories SET status='closed',last_item_at=? WHERE id=?", (stamp(older), sid))
        db.conn().commit()
        item = self.item()
        with patch.object(embeddings, "embed", side_effect=self.vectors):
            candidates = await stories.placement_candidates(item, NOW)
        self.assertIn(sid, [s.id for s in candidates])
        with patch.object(stories.openrouter, "chat_json", return_value={"story": 1, "reason": "same yield climb"}) as model:
            chosen, _, okay = await stories.place(item, candidates, NOW)
        self.assertTrue(okay)
        self.assertEqual(chosen.id, sid)
        self.assertIn(OLD, model.call_args.kwargs["user"])
        with patch.object(db, "now_iso", return_value=stamp(NOW)):
            db.attach_item_to_story(item["id"], sid)
        row = db.get_story(sid)
        self.assertEqual(row["status"], "live")
        self.assertEqual(row["first_at"], stamp(older))
        self.assertEqual(row["reopened_at"], stamp(NOW))
        self.assertTrue(stories.load_one(sid, NOW).posts)
        with patch.object(db, "now_iso", return_value=stamp(NOW)):
            self.assertEqual(db.close_stale_stories(120, 168), [])
        self.assertEqual(db.get_item(seed["id"])["status"], "expired")

    async def test_live_stories_are_not_hidden_by_newer_thirty(self):
        for n in range(35):
            item = self.item(f"Unrelated situation {n}")
            db.create_story(headline=item["title"], summary=item["title"], item_id=item["id"], at=stamp(NOW))
        with patch.object(embeddings, "embed", side_effect=self.vectors):
            candidates = await stories.placement_candidates(self.item(), NOW)
        self.assertEqual(len(candidates), 35)

    async def test_first_post_with_related_history_faces_gate(self):
        story = stories.Story(id=0, headline=NEW, pending=[self.item()], first_at=NOW, last_item_at=NOW)
        with patch.object(stories, "_closest_published", return_value="Already published: " + OLD), \
             patch.object(stories.openrouter, "chat_json", return_value={"verdict": "hold", "angle": "", "reason": "same climb"}) as judge:
            result = await stories.should_post(story, NOW)
        self.assertEqual(result["verdict"], "hold")
        judge.assert_awaited_once()

    async def test_invalid_story_choice_is_retry_not_new_story(self):
        story = stories.Story(id=1, headline=OLD, summary=OLD, last_item_at=NOW)
        with patch.object(stories.openrouter, "chat_json", return_value={"story": 999, "reason": "bad index"}):
            _, _, okay = await stories.place(self.item(), [story], NOW)
        self.assertFalse(okay)

    async def test_rehearsal_model_outage_does_not_write_live_counters(self):
        story = stories.Story(id=1, headline=OLD, summary=OLD, last_item_at=NOW)
        before = list(db.conn().execute("SELECT * FROM counters"))
        with patch.object(stories.openrouter, "chat_json", side_effect=RuntimeError("offline")):
            _, _, available = await stories.place(self.item(), [story], NOW, persist=False)
            self.assertFalse(available)
            story.pending = [self.item()]
            with patch.object(stories, "_closest_published", return_value="known history"):
                await stories.should_post(story, NOW, persist=False)
        self.assertEqual(list(db.conn().execute("SELECT * FROM counters")), before)

    async def test_mixed_yield_roundup_cannot_send_with_fractional_threshold_and_record_claims(self):
        old = "US 30-year Treasury yield rises to 5.656%. US 10-year Treasury yield touches 5.304%."
        answer = {"verdict": "send", "reason": "5.7 is a new whole-percent threshold",
                  "covered_claims": [], "new_claims": [
                      novelty("whole_percent_threshold", "The 30-year yield crossed 5.7%", old,
                              "5.7", "5.7", "5.656"),
                      novelty("record", "the 10-year yield reached a fresh 24-year high of 5.3493%", old)]}
        with patch.object(echo.openrouter, "chat_json", return_value=answer):
            result = await echo._judge_history(ROUNDUP, old, persist=False)
        self.assertEqual(result["verdict"], "hold")

    async def test_model_cannot_round_5_7_up_to_6_to_pass_threshold_validation(self):
        old = "US 30-year Treasury yield rises to 5.656%"
        answer = {"verdict": "send", "reason": "crossed 6%", "covered_claims": [],
                  "new_claims": [novelty("whole_percent_threshold", "The 30-year yield crossed 5.7%", old,
                                        "6", "5.7", "5.656")]}
        with patch.object(echo.openrouter, "chat_json", return_value=answer):
            self.assertEqual((await echo._judge_history(ROUNDUP, old, persist=False))["verdict"], "hold")

    async def test_10_year_doing_same_us_curve_move_is_not_a_new_actor(self):
        old = "US 30-year Treasury yield rises to 5.656%"
        answer = {"verdict": "send", "reason": "new actor is 10-year", "covered_claims": [],
                  "new_claims": [novelty("new_actor", "the 10-year yield reached a fresh 24-year high of 5.3493%", old)]}
        with patch.object(echo.openrouter, "chat_json", return_value=answer):
            self.assertEqual((await echo._judge_history(ROUNDUP, old, persist=False))["verdict"], "hold")

    async def test_valid_whole_percent_threshold_remains_eligible(self):
        new = "US 30-year Treasury yield crosses 6% for the first time"
        old = "US 30-year Treasury yield rises to 5.656%"
        answer = {"verdict": "send", "reason": "first actual 6% crossing", "covered_claims": [],
                  "new_claims": [novelty("whole_percent_threshold", new, old, "6", "6", "5.656")]}
        with patch.object(echo.openrouter, "chat_json", return_value=answer):
            self.assertEqual((await echo._judge_history(new, old, persist=False))["verdict"], "send")

    async def test_invalid_crossing_is_refused_even_with_paraphrased_prior_quote(self):
        old = "US 30-year Treasury yield rises to 5.656%"
        answer = {"verdict": "send", "reason": "crossed 6%", "covered_claims": [],
                  "new_claims": [novelty("whole_percent_threshold", "The 30-year yield crossed 5.7%",
                                        "The 30-year yield rises to 5.656%", "6", "5.7", "5.656")]}
        with patch.object(echo.openrouter, "chat_json", return_value=answer):
            self.assertEqual((await echo._judge_history(ROUNDUP, old, persist=False))["verdict"], "hold")

    async def test_valid_crossing_cannot_use_fabricated_prior_evidence(self):
        from utils import semantic_memory as memory
        new = "US 30-year Treasury yield crosses 6% for the first time"
        old = "US 30-year Treasury yield rises to 5.656%"
        answer = {"verdict": "send", "reason": "crossed 6%", "covered_claims": [],
                  "new_claims": [novelty("whole_percent_threshold", new,
                                        "The 30-year yield rises to 5.656%", "6", "6", "5.656")]}
        with patch.object(echo.openrouter, "chat_json", return_value=answer):
            with self.assertRaises(memory.Unavailable):
                await echo._judge_history(new, old, persist=False)

    async def test_reading_repeat_with_a_real_policy_change_is_not_held(self):
        new = ROUNDUP+" The Fed announced an emergency bond purchase program."
        old = "US 30-year Treasury yield rises to 5.656%"
        answer = {"verdict": "send", "reason": "policy changed", "covered_claims": [], "new_claims": [
            novelty("whole_percent_threshold", "The 30-year yield crossed 5.7%", old, "5.7", "5.7", "5.656"),
            novelty("decision", "The Fed announced an emergency bond purchase program.")]}
        with patch.object(echo.openrouter, "chat_json", return_value=answer):
            self.assertEqual((await echo._judge_history(new, old, persist=False))["verdict"], "send")

    async def test_unquoted_novelty_is_not_an_approval(self):
        from utils import semantic_memory as memory
        answer = {"verdict": "send", "reason": "policy changed", "covered_claims": [],
                  "new_claims": [novelty("decision", "The Fed announced emergency purchases.")]}
        with patch.object(echo.openrouter, "chat_json", return_value=answer):
            with self.assertRaises(memory.Unavailable):
                await echo._judge_history(ROUNDUP, OLD, persist=False)

    async def test_reading_cannot_escape_as_a_decision_period_or_magnitude(self):
        old = "US 30-year Treasury yield rises to 5.656%"
        for kind in ("decision", "new_period", "magnitude", "new_fact"):
            with self.subTest(kind=kind):
                answer = {"verdict": "send", "reason": "new landmark", "covered_claims": [],
                          "new_claims": [novelty(kind, "crossed 5.7% for the first time since 2002", old)]}
                with patch.object(echo.openrouter, "chat_json", return_value=answer):
                    self.assertEqual((await echo._judge_history(ROUNDUP, old, persist=False))["verdict"], "hold")

    async def test_reversal_quotes_can_use_the_surrounding_literal_clause(self):
        new = "Bitcoin ETFs saw $120m outflows."
        old = "Bitcoin ETFs saw $643m inflows."
        answer = {"verdict": "send", "reason": "direction reversed", "covered_claims": [],
                  "new_claims": [novelty("reversal", "$120m", "$643m")]}
        with patch.object(echo.openrouter, "chat_json", return_value=answer):
            self.assertEqual((await echo._judge_history(new, old, persist=False))["verdict"], "send")

    async def test_fall_after_a_quoted_yield_high_is_a_reversal(self):
        new = "US 30-year Treasury yield falls to 5.2%"
        old = "The 30-year yield reached 5.59%, the highest since 2001."
        answer = {"verdict": "send", "reason": "direction reversed", "covered_claims": [],
                  "new_claims": [novelty("reversal", new, old)]}
        with patch.object(echo.openrouter, "chat_json", return_value=answer):
            self.assertEqual((await echo._judge_history(new, old, persist=False))["verdict"], "send")

    async def test_explicit_yield_fall_can_reference_a_neutral_higher_prior_level(self):
        new = "US 30-year Treasury yield falls to 5.2%"
        old = "US 30-year Treasury yield reaches 5.367%"
        history = old + "\nUS 30-year Treasury yield rises to 5.59%."
        answer = {"verdict": "send", "reason": "fall after the known run", "covered_claims": [],
                  "new_claims": [novelty("reversal", new, old)]}
        with patch.object(echo.openrouter, "chat_json", return_value=answer):
            self.assertEqual((await echo._judge_history(new, history, persist=False))["verdict"], "send")

    async def test_unused_coverage_does_not_block_a_grounded_single_batch_send(self):
        new = "The Fed announced an emergency bond purchase program."
        answer = {"verdict": "send", "reason": "new policy", "covered_claims": ["paraphrased old news"],
                  "new_claims": [novelty("decision", new)]}
        with patch.object(echo.openrouter, "chat_json", return_value=answer):
            self.assertEqual((await echo._judge_history(new, OLD, persist=False))["verdict"], "send")

    async def test_multi_batch_coverage_must_still_be_literal(self):
        from utils import semantic_memory as memory
        new = "The Fed announced an emergency bond purchase program."
        answer = {"verdict": "send", "reason": "new policy", "covered_claims": ["paraphrased old news"],
                  "new_claims": [novelty("decision", new)]}
        with patch.object(echo.openrouter, "chat_json", return_value=answer):
            with self.assertRaises(memory.Unavailable):
                await echo._judge_history(new, OLD, persist=False, extract_coverage=True)


class EmbeddingResponse(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_or_missing_batch_indices_are_rejected(self):
        response = unittest.mock.Mock(status_code=200)
        response.json.return_value = {"data": [{"index": 0, "embedding": [1, 0]},
                                                {"index": 0, "embedding": [0, 1]}]}
        client = AsyncMock()
        client.post.return_value = response
        with patch.object(embeddings.httpx, "AsyncClient") as factory:
            factory.return_value.__aenter__.return_value = client
            self.assertIsNone(await embeddings._embed_batch(["first", "second"]))


if __name__ == "__main__":
    unittest.main()
