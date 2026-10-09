"""GET /api/v1/posts — paginated feed of items flowing through the pipeline.

Reads the `items` table (not `posts` — an item may never reach the posts
table, e.g. if it was rejected before writing), which is what carries all the
columns the frontend table needs: source, title, kind, company, status. `body`
and `status_reason` are included too, so the frontend's expandable row can
show the full item text and the pipeline's reason without a second request.

With no database yet it returns an empty-but-valid response with "ready": false instead of a 503 or 500 — see
paths.database_ready().

Filters combine with AND: ?source= picks one source, ?status= takes a
comma-separated list of raw item statuses (published,held,...), and ?q= is
a keyword search over title and body — every word must appear somewhere,
case-insensitively, so "iran oil" finds items mentioning both. The response
also carries status_counts: how many items match source + q per status,
ignoring the status filter, so the frontend's status chips can show what
each one would give you before it is clicked.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Query

import paths
from db_connector import query

router = APIRouter()

_TAG_RE = re.compile(r"<[^>]+>")


# Longest keyword search accepted. A search box, not a query language — this
# only stops a pasted essay from becoming a hundred LIKE clauses.
_MAX_TERMS = 8


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/posts")
def get_posts(
    source: str | None = Query(default=None, description="Filter by source_name"),
    status: str | None = Query(default=None, description="Comma-separated item statuses"),
    q: str | None = Query(default=None, max_length=200, description="Keywords, all must match"),
    company: str | None = Query(default=None, description="Filter by the company that made it"),
    kind: str | None = Query(default=None, description="Filter by kind (stored in items.topic)"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):

    if not paths.database_ready():
        return {
            "ready": False,
            "items": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
            "status_counts": {},
        }

    # Everything except the status filter — shared by the counts query, so a
    # chip's number means "what you get if you add this status".
    clauses: list[str] = []
    params: list = []
    if source:
        clauses.append("source_name = ?")
        params.append(source)
    if company:
        clauses.append("company = ?")
        params.append(company)
    if kind:
        clauses.append("topic = ?")
        params.append(kind)
    for term in (q or "").split()[:_MAX_TERMS]:
        pattern = f"%{_escape_like(term)}%"
        clauses.append("(title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')")
        params.extend([pattern, pattern])

    base_where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    count_rows = query(
        f"SELECT status, COUNT(*) AS n FROM items {base_where} GROUP BY status",
        tuple(params),
    )
    status_counts = {row["status"]: row["n"] for row in count_rows}

    statuses = [s.strip() for s in (status or "").split(",") if s.strip()]
    if statuses:
        clauses.append(f"status IN ({','.join('?' * len(statuses))})")
        params.extend(statuses)
        total = sum(status_counts.get(s, 0) for s in set(statuses))
    else:
        total = sum(status_counts.values())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    # The editor's own words are the answer to "why?" for a published item, where
    # status_reason only ever says "sent as message N". The last decision is the
    # one that counts: a rewritten post is judged twice and only the final
    # verdict decided whether it went out.
    rows = query(
        f"""
        SELECT id, fetched_at AS time, source_name, title, body, url, story_id,
               status, status_reason, importance, market, topic, company, sorter_reason,
               (SELECT p.telegram_message_id FROM posts p
                 WHERE p.item_id = items.id AND p.status = 'sent'
                   AND p.telegram_message_id IS NOT NULL
                 ORDER BY p.id DESC LIMIT 1)          AS telegram_message_id,
               (SELECT p.post_html FROM posts p
                 WHERE p.item_id = items.id ORDER BY p.id DESC LIMIT 1)
                                                      AS post_html,
               (SELECT e.verdict FROM editor_decisions e
                 WHERE e.item_id = items.id ORDER BY e.id DESC LIMIT 1)
                                                      AS editor_verdict,
               (SELECT e.reason FROM editor_decisions e
                 WHERE e.item_id = items.id ORDER BY e.id DESC LIMIT 1)
                                                      AS editor_reason,
               (SELECT e.confidence FROM editor_decisions e
                 WHERE e.item_id = items.id ORDER BY e.id DESC LIMIT 1)
                                                      AS editor_confidence,
               (SELECT e.attempt FROM editor_decisions e
                 WHERE e.item_id = items.id ORDER BY e.id DESC LIMIT 1)
                                                      AS editor_attempt
        FROM items
        {where}
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    )

    # Built here rather than in the browser: only this side knows the channel's
    # @name, and a channel without one (a numeric id) must simply get no
    # link instead of a broken one.
    username = paths.channel_username()
    for row in rows:
        # The post as the reader saw it (or would have): Telegram's <b> and links dropped.
        row["post_text"] = _TAG_RE.sub("", row.pop("post_html") or "").strip()
        message_id = row.get("telegram_message_id")
        row["telegram_url"] = (f"https://t.me/{username}/{message_id}"
                               if username and message_id else None)

    return {
        "ready": True,
        "items": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "status_counts": status_counts,
    }
