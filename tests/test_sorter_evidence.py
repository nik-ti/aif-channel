"""Publication needs source evidence even when the model gives a high score."""

import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from nodes import sorter
from pipeline import graph, stations
from utils import db, openrouter

QUOTE = "You can paste the prompt into ChatGPT to extract receipt totals into a table."
ITEM = {"id": 1, "origin": "rss", "source_name": "any_source", "topic": "skill",
        "company": "other", "title": "A receipt assistant", "body": QUOTE,
        "article_text": QUOTE + " It includes steps for checking currencies, missing dates, "
        "and duplicate receipts. The free prompt can be copied from the guide and used "
        "without installing software. This resource was published last year."}
ANSWER = {"relevant": True, "basis": "resource", "evidence": QUOTE,
          config.SORTER_AXIS: "business", "importance": 5, "reason": "A usable receipt workflow"}


class EvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def judge(self, answer, item=ITEM):
        with patch.object(openrouter, "chat_json", new_callable=AsyncMock,
                          return_value=answer) as call:
            result = await sorter.execute(item)
        call.assert_awaited_once()
        return result

    async def test_missing_or_empty_evidence_blocks_a_high_score(self):
        answer = {key: value for key, value in ANSWER.items() if key != "evidence"}
        self.assertFalse((await self.judge(answer))["relevant"])
        for value in (None, "", " \n ", 42, []):
            answer = {**ANSWER, "evidence": value}
            result = await self.judge(answer)
            self.assertFalse(result["relevant"], result)
            self.assertFalse(result["fallback"])
            self.assertIn("evidence", result["reason"])

    async def test_missing_or_none_basis_blocks_a_high_score(self):
        for value in (None, "none", "launch", []):
            result = await self.judge({**ANSWER, "basis": value})
            self.assertFalse(result["relevant"], result)
            self.assertFalse(result["fallback"])

    async def test_fabricated_or_changed_number_quote_blocks(self):
        for quote in ("A new model was released today.", QUOTE.replace("receipt", "invoice"),
                      "The context window increased to 500000 tokens."):
            result = await self.judge({**ANSWER, "evidence": quote},
                                     {**ITEM, "body": "The context window increased to 50000 tokens."})
            self.assertFalse(result["relevant"], result)
            self.assertIn("absent", result["reason"])

    async def test_old_useful_resource_with_real_quote_passes(self):
        result = await self.judge(ANSWER)
        self.assertTrue(result["relevant"], result)
        self.assertEqual(result["basis"], "resource")
        self.assertEqual(result["evidence"], QUOTE)
        self.assertIn(QUOTE, result["reason"])

    async def test_genuine_change_with_real_quote_passes(self):
        result = await self.judge({**ANSWER, "basis": "news"})
        self.assertTrue(result["relevant"])
        self.assertEqual(result["basis"], "news")

    async def test_only_whitespace_entities_and_unicode_composition_are_normalized(self):
        quote = "Cafe\u0301 & report totals are available now."
        result = await self.judge({**ANSWER, "evidence": quote},
                                 {**ITEM, "body": "Café &amp; report\n totals are available now."})
        self.assertTrue(result["relevant"], result)

    async def test_prompt_metadata_and_unseen_article_tail_are_not_evidence(self):
        for quote in ("Made by: other", "Kind: skill", "Source: vendor | Release date: 2026-10-12",
                      "Hidden final detail is here."):
            item = {**ITEM, "body": "Source: vendor | Release date: 2026-10-12",
                    "article_text": "A" * 2200 + " Hidden final detail is here."}
            result = await self.judge({**ANSWER, "evidence": quote}, item)
            self.assertFalse(result["relevant"], result)

    async def test_existing_irrelevant_decision_cannot_be_overridden_by_valid_quote(self):
        result = await self.judge({**ANSWER, "relevant": False})
        self.assertFalse(result["relevant"])

    async def test_model_outage_still_retries(self):
        with patch.object(openrouter, "chat_json", side_effect=RuntimeError("offline")):
            result = await sorter.execute(ITEM)
        self.assertTrue(result["fallback"])
        self.assertFalse(result["relevant"])

    def test_schema_requires_exactly_two_new_fields(self):
        self.assertEqual(set(sorter.SCHEMA["required"]),
                         {"relevant", "basis", "evidence", config.SORTER_AXIS, "importance", "reason"})

    async def test_accepted_quote_is_stored_in_full_for_dashboard_review(self):
        with ExitStack() as stack:
            folder = stack.enter_context(tempfile.TemporaryDirectory())
            stack.enter_context(patch.object(config, "DB_PATH", Path(folder) / "test.db"))
            stack.enter_context(patch.object(db, "_conn", None))
            db.init_db()
            ident = db.insert_item(origin="rss", source_name="any_source", external_id="stored-quote",
                                   url="", title=ITEM["title"], body=ITEM["body"])
            db.set_article_text(ident, ITEM["article_text"])
            try:
                for market in ("business", "none"):
                    with patch.object(openrouter, "chat_json", new_callable=AsyncMock,
                                      return_value={**ANSWER, config.SORTER_AXIS: market,
                                                    "reason": "A concrete usable workflow. " * 10}):
                        await stations.sorter_node({"item": dict(db.get_item(ident))})
                    self.assertIn(QUOTE, db.get_item(ident)["sorter_reason"])
            finally:
                db.conn().close()

    async def test_missing_evidence_stops_graph_before_writer_and_publisher(self):
        with ExitStack() as stack:
            folder = stack.enter_context(tempfile.TemporaryDirectory())
            stack.enter_context(patch.object(config, "DB_PATH", Path(folder) / "test.db"))
            stack.enter_context(patch.object(db, "_conn", None))
            db.init_db()
            ident = db.insert_item(origin="rss", source_name="any_source", external_id="evidence-test",
                                   url="", title=ITEM["title"], body=ITEM["body"])
            stack.enter_context(patch.object(stations, "dedup_node", new_callable=AsyncMock, return_value={}))
            stack.enter_context(patch.object(stations, "fetch_article_node", new_callable=AsyncMock, return_value={}))
            stack.enter_context(patch.object(stations, "labeler_node", new_callable=AsyncMock, return_value={}))
            stack.enter_context(patch.object(openrouter, "chat_json", new_callable=AsyncMock,
                                            return_value={**ANSWER, "evidence": ""}))
            writer = stack.enter_context(patch.object(stations, "writer_node", new_callable=AsyncMock,
                                                      side_effect=AssertionError("reached writer")))
            publish = stack.enter_context(patch.object(stations, "publish_node", new_callable=AsyncMock,
                                                       side_effect=AssertionError("reached publish")))
            try:
                result = await graph.build_graph().ainvoke({"item": dict(db.get_item(ident))})
                self.assertEqual(result["outcome"], "irrelevant")
                self.assertEqual(db.get_item(ident)["status"], "irrelevant")
                writer.assert_not_awaited()
                publish.assert_not_awaited()
            finally:
                db.conn().close()


if __name__ == "__main__":
    unittest.main()
