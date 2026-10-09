"""GET /api/v1/companies — the company limit at a glance: today's posts per company, the items
waiting for tonight's digest, and the digests already sent. Replaces the old /stories.
The limit and the digest hour are read from config.py and .env as text, like /nodes does.
"""

from __future__ import annotations

import os
import re

from fastapi import APIRouter

import paths
from db_connector import query

router = APIRouter()

_TAG_RE = re.compile(r"<[^>]+>")


def _setting(name: str, default: int) -> int:
    """An integer setting: .env first, then config.py's default."""
    value = paths.env().get(name) or os.environ.get(name)
    if not value:
        try:
            text = (paths.ROOT_DIR / "config.py").read_text(encoding="utf-8")
            match = re.search(rf'^{name}\s*=\s*_get_int\(\s*"{name}"\s*,\s*(\d+)', text, re.MULTILINE)
            value = match.group(1) if match else None
        except OSError:
            value = None
    try:
        return int(value) if value else default
    except ValueError:
        return default


@router.get("/companies")
def get_companies():
    limit = _setting("COMPANY_DAILY_LIMIT", 2)
    digest_hour = _setting("DIGEST_HOUR_UTC", 18)
    if not paths.database_ready():
        return {"ready": False, "limit": limit, "digest_hour_utc": digest_hour,
                "today": [], "waiting": [], "digests": []}

    today = query(
        """
        SELECT i.company AS company, COUNT(*) AS posts_today
        FROM posts p JOIN items i ON i.id = p.item_id
        WHERE p.status = 'sent' AND p.sent_at >= date('now') AND i.company != ''
        GROUP BY i.company
        """
    )
    waiting = query(
        """
        SELECT id, title, company, topic AS kind, importance, fetched_at AS time, status_reason
        FROM items WHERE status = 'waiting_digest' ORDER BY company, id
        """
    )
    counts = {row["company"]: {"company": row["company"], "posts_today": row["posts_today"],
                               "waiting": 0} for row in today}
    for row in waiting:
        entry = counts.setdefault(row["company"], {"company": row["company"], "posts_today": 0,
                                                   "waiting": 0})
        entry["waiting"] += 1

    username = paths.channel_username()
    digests = query(
        """
        SELECT p.id, p.item_id, p.sent_at, p.post_html, p.telegram_message_id, i.company
        FROM posts p JOIN items i ON i.id = p.item_id
        WHERE p.status = 'sent' AND p.topic = 'digest'
        ORDER BY p.id DESC LIMIT 20
        """
    )
    for row in digests:
        row["text"] = _TAG_RE.sub("", row.pop("post_html") or "").strip()
        message_id = row.pop("telegram_message_id")
        row["telegram_url"] = (f"https://t.me/{username}/{message_id}"
                               if username and message_id else None)
        row["items"] = query(
            "SELECT id, title FROM items WHERE id = ? OR status_reason = ? ORDER BY id",
            (row["item_id"], f"in the company digest sent with item {row['item_id']}"),
        )

    return {
        "ready": True,
        "limit": limit,
        "digest_hour_utc": digest_hour,
        "today": sorted(counts.values(), key=lambda r: (-r["posts_today"], r["company"])),
        "waiting": waiting,
        "digests": digests,
    }
