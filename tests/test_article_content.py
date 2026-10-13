"""Article collection preserves content; the sorter judges videos and resources."""

import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from nodes import article
from pipeline import graph, stations
from utils import db

URL = "https://ai-tldr.dev/releases/example-video/"
HTML = '<script type="application/ld+json">{"@type":"NewsArticle","articleSection":"video"}</script>'


class ArticleContentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.patches = ExitStack()
        folder = self.patches.enter_context(tempfile.TemporaryDirectory())
        self.patches.enter_context(patch.object(config, "DB_PATH", Path(folder) / "test.db"))
        self.patches.enter_context(patch.object(db, "_conn", None))
        db.init_db()
        ident = db.insert_item(origin="rss", source_name="ai_tldr", external_id=URL,
                               url=URL, title="An official video announcement")
        self.item = dict(db.get_item(ident))

    def tearDown(self):
        db.conn().close()
        self.patches.close()

    async def test_video_category_reaches_sorter_instead_of_being_blanket_rejected(self):
        text = "An official launch video with detailed access instructions. " * 10
        with patch.object(article, "_read", new_callable=AsyncMock, return_value=(text, HTML, "plain")):
            result = await stations.fetch_article_node({"item": self.item})
        self.assertNotIn("outcome", result)
        self.assertEqual(result["item"]["article_text"], text.strip())
        self.assertEqual(stations.route_after_fetch_article(result), "read")

    async def test_cached_article_is_reused_without_an_extra_category_request(self):
        with patch.object(article, "_plain", new_callable=AsyncMock) as fetch:
            result = await article.fetch_for({**self.item, "article_text": "Cached source content."})
        self.assertEqual(result, "Cached source content.")
        fetch.assert_not_awaited()

    async def test_failed_fallbacks_keep_original_html_for_dates_and_media(self):
        with patch.object(article, "_plain", new_callable=AsyncMock, return_value=(None, HTML)), \
                patch.object(article, "_browser", new_callable=AsyncMock, return_value=(None, "")), \
                patch.object(article, "_reader", new_callable=AsyncMock, return_value=None):
            text, html, _ = await article._read(URL)
        self.assertIsNone(text)
        self.assertEqual(html, HTML)

    async def test_launch_with_embedded_demo_reaches_next_station(self):
        html = '<video src="https://example.com/demo.mp4"></video>'
        with patch.object(article, "_read", new_callable=AsyncMock,
                          return_value=("A real launch. " * 40, html, "plain")):
            result = await stations.fetch_article_node({"item": self.item})
        self.assertNotIn("outcome", result)

    def test_diagram_does_not_claim_to_reject_video_categories(self):
        self.assertNotIn("video intro", graph.diagram())


if __name__ == "__main__":
    unittest.main()
