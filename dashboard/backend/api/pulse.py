"""GET /api/v1/pulse — the few numbers the header shows on every tab: is the channel
alive (when it last read an item, when it last posted), how much went out today, and
what is waiting. Cheap on purpose, since every open tab polls it.
"""

from __future__ import annotations

from fastapi import APIRouter

import paths
from db_connector import query_one

router = APIRouter()


def _value(sql: str):
    row = query_one(sql)
    return row["v"] if row else None


@router.get("/pulse")
def get_pulse():
    if not paths.database_ready():
        return {"ready": False}
    return {
        "ready": True,
        # The feeds are polled every 10 minutes whether or not anything is new, so
        # this is the heartbeat: older than ~25 minutes means the channel is down.
        "last_check_at": _value("SELECT MAX(last_checked_at) AS v FROM sources"),
        "last_item_at": _value("SELECT MAX(fetched_at) AS v FROM items"),
        "last_post_at": _value("SELECT MAX(sent_at) AS v FROM posts WHERE status = 'sent'"),
        "posts_today": _value(
            "SELECT COUNT(*) AS v FROM posts WHERE status = 'sent' AND sent_at >= date('now')") or 0,
        "in_progress": _value(
            "SELECT COUNT(*) AS v FROM items WHERE status IN ('queued', 'written')") or 0,
        "waiting_digest": _value(
            "SELECT COUNT(*) AS v FROM items WHERE status = 'waiting_digest'") or 0,
    }
