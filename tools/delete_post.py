"""Delete posts that already went out: removed from the channel and marked 'deleted' in the
database, so the repeat check and the follow-up search stop counting them as told.

    python3 tools/delete_post.py ITEM_ID [ITEM_ID ...] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from utils import db, persona_loader, telegram_client  # noqa: E402


async def delete(item_ids: list[int], dry_run: bool) -> None:
    bot = None if dry_run else await telegram_client._get_bot()
    for item_id in item_ids:
        post = db.conn().execute(
            "SELECT * FROM posts WHERE item_id = ? AND status = 'sent'", (item_id,)).fetchone()
        if post is None or not post["telegram_message_id"]:
            print(f"Item {item_id}: no sent post with a message number, skipped")
            continue
        message_id = post["telegram_message_id"]
        first_line = persona_loader.visible_text(post["post_html"]).strip().splitlines()[0]
        print(f"Item {item_id}, message {message_id}: {first_line[:90]}")
        if dry_run:
            continue
        await bot.delete_message(chat_id=config.CHANNEL_ID, message_id=message_id)
        db.mark_message_deleted(message_id)
        print("  deleted")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("item_ids", type=int, nargs="+")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(delete(args.item_ids, args.dry_run))
