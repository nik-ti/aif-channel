"""Regression checks for multi-source macro attribution; no network or live writes."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from nodes import stories, calendar
from unittest.mock import patch
from datetime import datetime, timezone
from utils import db

class MacroSources(unittest.TestCase):
    def test_headline_inflation_is_not_matched_to_core_mentioned_in_body(self):
        events = [{"title": "Core CPI Flash Estimate y/y", "country": "EUR", "at_utc": "2026-10-02 09:00:00"},
                  {"title": "CPI Flash Estimate y/y", "country": "EUR", "at_utc": "2026-10-02 09:00:00"}]
        when = datetime(2026, 10, 2, 9, 1, tzinfo=timezone.utc)
        with patch.object(db, "calendar_between", return_value=events):
            found = calendar.match("Eurozone inflation 3.8%; core inflation 2.5%", when,
                                   headline="Eurozone inflation 3.8%")
        self.assertEqual(found["title"], "CPI Flash Estimate y/y")

    def test_folded_post_keeps_both_sources_after_reopening_database(self):
        with tempfile.TemporaryDirectory() as directory:
            old_path, old_conn = config.DB_PATH, db._conn
            config.DB_PATH = Path(directory) / "test.db"
            db._conn = None
            try:
                db.init_db()
                items = []
                for name, body in [("BullTheoryio", "Stocks gained $700 billion; hike odds 16%."),
                                   ("protos", "Payroll revisions removed 60,000 jobs.")]:
                    ident = db.insert_item(origin="x", source_name=name, external_id=name,
                                           url=f"https://example.com/{name}", title=name, body=body)
                    items.append(dict(db.conn().execute("SELECT * FROM items WHERE id=?", (ident,)).fetchone()))
                story = stories.Story(id=1, headline="US jobs", pending=items)
                source = stories.as_source(story)
                ident = db.create_post(item_id=source["id"], topic="markets", post_html="Update",
                                       image_url="", writer_model="test", source_context={
                                           "source_items": source["source_items"], "body": source["body"]})
                db.conn().close()
                db._conn = None
                context = json.loads(db.conn().execute("SELECT source_context FROM posts WHERE id=?", (ident,)).fetchone()[0])
                self.assertEqual([s["source_name"] for s in context["source_items"]], ["BullTheoryio", "protos"])
                self.assertIn("[BullTheoryio]", context["body"])
                self.assertIn("700 billion", context["body"])
                self.assertEqual(context["source_items"][0]["url"], "https://example.com/BullTheoryio")
            finally:
                if db._conn:
                    db._conn.close()
                config.DB_PATH, db._conn = old_path, old_conn

if __name__ == "__main__":
    unittest.main()
