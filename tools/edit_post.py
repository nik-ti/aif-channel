"""Fix a post that already went out: new text and/or a new link, edited in place in the
channel and saved to the database, so the dashboard and the repeat check see the fixed version.
The text is the writer's HTML with href="LINK"; the link line and signature are added as usual.

    python3 tools/edit_post.py ITEM_ID --html new_post.html [--link URL | --no-link] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from nodes import publisher  # noqa: E402
from utils import db, telegram_client, telegram_html  # noqa: E402


async def edit(item_id: int, html: str | None, link: str | None, dry_run: bool) -> None:
    post = db.conn().execute(
        "SELECT * FROM posts WHERE item_id = ? AND status = 'sent'", (item_id,)).fetchone()
    item = db.get_item(item_id)
    if post is None or item is None:
        sys.exit(f"No sent post for item {item_id}")
    html = html if html is not None else post["post_html"]
    link_url = (item["link_url"] or "") if link is None else link
    # No link at all: no source address either, so the publisher drops the link line.
    url = "" if link == "" else (item["url"] or "")
    message = publisher.compose(html, url, link_url, item["topic"] or "")
    print(f"--- message {post['telegram_message_id']} becomes:\n{message}\n")
    if dry_run:
        return

    bot = await telegram_client._get_bot()
    has_media = bool(post["media_image_url"] or post["media_video_url"])
    if has_media:
        await bot.edit_message_caption(
            chat_id=config.CHANNEL_ID, message_id=post["telegram_message_id"], parse_mode="HTML",
            caption=telegram_html.safe_truncate(telegram_html.sanitize(message), telegram_html.CAPTION_LIMIT))
    else:
        await bot.edit_message_text(
            chat_id=config.CHANNEL_ID, message_id=post["telegram_message_id"], parse_mode="HTML",
            text=telegram_html.safe_truncate(telegram_html.sanitize(message), telegram_html.TEXT_LIMIT),
            disable_web_page_preview=True)
    db.conn().execute("UPDATE posts SET post_html = ?, char_count = ? WHERE id = ?",
                      (html, len(html), post["id"]))
    db.conn().execute("UPDATE items SET link_url = ? WHERE id = ?", (link_url, item_id))
    db.conn().commit()
    print(f"Edited message {post['telegram_message_id']} (item {item_id}).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("item_id", type=int)
    parser.add_argument("--html", help="file with the new post text (writer HTML)")
    parser.add_argument("--link", help="the address the link line should open")
    parser.add_argument("--no-link", action="store_true", help="remove the link line")
    parser.add_argument("--dry-run", action="store_true", help="show the new message, change nothing")
    args = parser.parse_args()
    text = Path(args.html).read_text().strip() if args.html else None
    asyncio.run(edit(args.item_id, text, "" if args.no_link else args.link, args.dry_run))
