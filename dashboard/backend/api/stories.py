"""GET /api/v1/stories lists every story with item/post counts computed live from the database (not cached on the story row, matching nodes/stories.py).
Includes the full list of posts so the dashboard can show what happened to each piece of news without a second request.
Takes optional ?channel= (defaults to markets). A channel with no database yet returns a valid response with "ready": false."""

from __future__ import annotations

import re

from fastapi import APIRouter, Query

import paths
from channel_resolver import resolve_channel
from db_connector import query

router = APIRouter()

# Only these statuses get their own color. All others (irrelevant, low_impact,
# duplicate, failed, expired) read as "rejected" to readers.
_DISPLAY_STATUSES = {"published", "merged", "held"}

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Remove HTML tags (post_html only uses <b> for Telegram formatting).
    the dashboard shows plain text, matching how it shows item bodies."""
    return _TAG_RE.sub("", text).strip()


def _display_status(item_status: str) -> str:
    return item_status if item_status in _DISPLAY_STATUSES else "rejected"


@router.get("/stories")
def get_stories(channel: str | None = Query(default=None, description="Which channel's database to read")):
    name = resolve_channel(channel)

    if not paths.database_ready(name):
        return {"channel": name, "ready": False, "stories": []}

    story_rows = query(
        """
        SELECT
            s.id,
            s.headline,
            s.name,
            s.first_at,
            s.summary,
            s.status,
            s.last_post_at,
            (SELECT COUNT(*) FROM items i WHERE i.story_id = s.id) AS item_count,
            -- Only what actually reached Telegram. Counting every posts row
            -- made a story whose only draft the editor rejected read as
            -- "1 posted of 1 item" while it had published nothing.
            (SELECT COUNT(*) FROM posts p
                JOIN items i2 ON i2.id = p.item_id
                WHERE i2.story_id = s.id
                  AND p.status = 'sent' AND p.telegram_message_id IS NOT NULL) AS post_count,
            (SELECT COUNT(*) FROM posts p
                JOIN items i2 ON i2.id = p.item_id
                WHERE i2.story_id = s.id AND p.status = 'declined') AS declined_count
        FROM stories s
        ORDER BY s.last_item_at DESC
        """,
        channel=name,
    )

    # One query for every item belonging to any story, LEFT JOINed to its
    # post (if the item ever made it that far) — avoids an N+1 query per
    # story. post_html/post_url/telegram_message_id come along so `body`
    # and `status_reason` can prefer the actually-published text.
    item_rows = query(
        """
        SELECT
            i.id AS item_id,
            i.story_id,
            i.title,
            i.body AS item_body,
            i.status AS item_status,
            i.status_reason AS item_status_reason,
            i.sorter_reason,
            p.post_html,
            p.status AS post_status,
            p.telegram_message_id,
            (SELECT e.verdict FROM editor_decisions e
              WHERE e.item_id = i.id ORDER BY e.id DESC LIMIT 1) AS editor_verdict,
            (SELECT e.reason FROM editor_decisions e
              WHERE e.item_id = i.id ORDER BY e.id DESC LIMIT 1) AS editor_reason,
            (SELECT e.confidence FROM editor_decisions e
              WHERE e.item_id = i.id ORDER BY e.id DESC LIMIT 1) AS editor_confidence
        FROM items i
        LEFT JOIN posts p ON p.item_id = i.id
        WHERE i.story_id IS NOT NULL
        ORDER BY i.id ASC
        """,
        channel=name,
    )

    username = paths.channel_username(name)
    posts_by_story: dict[int, list[dict]] = {}
    for row in item_rows:
        body = _strip_html(row["post_html"]) if row["post_html"] else (row["item_body"] or "")
        message_id = row["telegram_message_id"]
        sent = row["post_status"] == "sent" and message_id
        entry = {
            "id": row["item_id"],
            "item_id": row["item_id"],
            "title": row["title"],
            "body": body,
            "status": _display_status(row["item_status"]),
            "status_reason": row["item_status_reason"] or "",
            "sorter_reason": row["sorter_reason"] or "",
            "telegram_url": (f"https://t.me/{username}/{message_id}"
                             if username and sent else None),
            "editor_verdict": row["editor_verdict"],
            "editor_reason": row["editor_reason"],
            "editor_confidence": row["editor_confidence"],
        }
        posts_by_story.setdefault(row["story_id"], []).append(entry)

    stories = []
    for row in story_rows:
        stories.append(
            {
                "id": row["id"],
                "headline": row["headline"],
                # A short name for the thread. Falls back to the opening
                # headline for stories that predate naming.
                "name": (row["name"] if "name" in row.keys() else "") or row["headline"],
                # When the story opened, so a card can say how long it has
                # been running and not only when it last spoke.
                "first_at": row["first_at"] if "first_at" in row.keys() else None,
                "summary": row["summary"],
                # "status" and "state" are the same underlying value
                # (live/closed) — the API spec asks for both field names.
                "status": row["status"],
                "state": row["status"],
                "item_count": row["item_count"],
                "post_count": row["post_count"],
                "declined_count": row["declined_count"] if "declined_count" in row.keys() else 0,
                "last_post_at": row["last_post_at"],
                "posts": posts_by_story.get(row["id"], []),
            }
        )

    return {"channel": name, "ready": True, "stories": stories}
