"""Every SQL statement in the project lives here.

Deliberately synchronous: the database is a local file and these queries finish
in under a millisecond, so do not make them async.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable

import config

logger = logging.getLogger("market-one-channel.db")

# Shared connection, created on first use (opening files costs more than queries).
_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    """Return open connection, creating on first call; WAL/busy_timeout must be set here,
    not schema.sql.
    """
    global _conn
    if _conn is None:
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(config.DB_PATH, timeout=10.0)

        # Rows as dicts (row["title"]) not tuples.
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode = WAL")
        _conn.execute("PRAGMA busy_timeout = 5000")
        _conn.execute("PRAGMA foreign_keys = ON")
    return _conn


def init_db() -> None:
    """Create missing tables/indexes from schema.sql; all use IF NOT EXISTS so it's safe
    to rerun.
    """
    schema = config.SCHEMA_PATH.read_text()
    conn().executescript(schema)
    conn().commit()
    _apply_migrations()
    logger.info("Database ready at %s", config.DB_PATH)


# Add columns here instead of schema.sql; existing DBs gain them on next start.
_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "items": [
        # Which market the sorter said has to reprice—see nodes/sorter.py.
        ("market", "ALTER TABLE items ADD COLUMN market TEXT DEFAULT ''"),
        ("continuation_of", "ALTER TABLE items ADD COLUMN continuation_of INTEGER DEFAULT NULL"),  # Dead since stories replaced it.
        ("story_id", "ALTER TABLE items ADD COLUMN story_id INTEGER DEFAULT NULL"),  # Not REFERENCES: no CASCADE with ALTER.
        ("video_url", "ALTER TABLE items ADD COLUMN video_url TEXT DEFAULT ''"),  # MP4 URL; image_url holds fallback thumbnail.
        ("video_kind", "ALTER TABLE items ADD COLUMN video_kind TEXT DEFAULT ''"),
        ("calendar_title", "ALTER TABLE items ADD COLUMN calendar_title TEXT DEFAULT ''"),  # Scheduled release data—see nodes/calendar.py.
        ("calendar_forecast", "ALTER TABLE items ADD COLUMN calendar_forecast TEXT DEFAULT ''"),
        ("calendar_previous", "ALTER TABLE items ADD COLUMN calendar_previous TEXT DEFAULT ''"),
        ("article_text", "ALTER TABLE items ADD COLUMN article_text TEXT DEFAULT ''"),  # Cached to avoid fetching URL twice—see nodes/article.py.
        ("forced", "ALTER TABLE items ADD COLUMN forced INTEGER DEFAULT 0"),  # Human override from dashboard; graph skips gate stations.
        ("calendar_key", "ALTER TABLE items ADD COLUMN calendar_key TEXT DEFAULT ''"),  # Stable name of the scheduled release—see calendar.key_for.
        ("sorter_reason", "ALTER TABLE items ADD COLUMN sorter_reason TEXT DEFAULT ''"),  # Why the sorter scored it so. status_reason only keeps this for items it REJECTED.
        ("media_json", "ALTER TABLE items ADD COLUMN media_json TEXT DEFAULT ''"),  # Every candidate image and video — see nodes/media.py.
        ("link_url", "ALTER TABLE items ADD COLUMN link_url TEXT DEFAULT ''"),  # The thing itself (repo, product page) when url is an aggregator's page.
    ],
    "posts": [
        ("source_context", "ALTER TABLE posts ADD COLUMN source_context TEXT DEFAULT ''"),
        # What the analysts chose. The publisher sends only these, so nothing unjudged goes out.
        ("media_checked", "ALTER TABLE posts ADD COLUMN media_checked INTEGER DEFAULT 0"),
        ("media_image_url", "ALTER TABLE posts ADD COLUMN media_image_url TEXT DEFAULT ''"),
        ("media_video_url", "ALTER TABLE posts ADD COLUMN media_video_url TEXT DEFAULT ''"),
        ("media_video_kind", "ALTER TABLE posts ADD COLUMN media_video_kind TEXT DEFAULT ''"),
        ("media_note", "ALTER TABLE posts ADD COLUMN media_note TEXT DEFAULT ''"),
    ],
    "stories": [
        ("name", "ALTER TABLE stories ADD COLUMN name TEXT DEFAULT ''"),  # Short name for dashboard/list (not headline/summary).
        ("calendar_key", "ALTER TABLE stories ADD COLUMN calendar_key TEXT DEFAULT ''"),  # Set when the story IS one scheduled release; placement then needs no model.
        ("roundup_asked_item_id", "ALTER TABLE stories ADD COLUMN roundup_asked_item_id INTEGER DEFAULT 0"),  # Newest held item the last roundup asked about; asked again only once a newer one joins.
    ],
}

# Indexes over migrated columns (cannot be in schema.sql: runs before migrations exist).
_MIGRATION_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_items_story ON items(story_id, status)",
]


def _apply_migrations() -> None:
    """Add any columns listed in _MIGRATIONS that this database doesn't have yet."""
    for table, changes in _MIGRATIONS.items():
        existing = {row["name"] for row in conn().execute(f"PRAGMA table_info({table})")}
        for column, statement in changes:
            if column not in existing:
                logger.info("Migrating: adding %s.%s", table, column)
                conn().execute(statement)

    for statement in _MIGRATION_INDEXES:
        conn().execute(statement)
    conn().commit()


def now_iso() -> str:
    """Current UTC time as 'YYYY-MM-DD HH:MM:SS'; everything in DB is UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def today_utc() -> str:
    """Today's date as 'YYYY-MM-DD' in UTC, used as the key for daily counters."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# SOURCES

def sync_sources(sources: Iterable[dict]) -> None:
    """Sync config.SOURCES into DB: add/refresh current feeds, disable removed ones, drop
    unpublished items from unconfigured feeds.
    """
    wanted = {s["name"] for s in sources}

    for source in sources:
        conn().execute(
            """
            INSERT INTO sources (name, url, kind, topic, enabled)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(name) DO UPDATE SET
                url = excluded.url,
                kind = excluded.kind,
                topic = excluded.topic,
                enabled = 1
            """,
            (source["name"], source["url"], source.get("kind", "rss"), source["topic"]),
        )

    # Switch off anything no longer in config.
    for row in conn().execute("SELECT name FROM sources WHERE enabled = 1"):
        if row["name"] not in wanted:
            logger.info("Source '%s' removed from config — disabling", row["name"])
            conn().execute("UPDATE sources SET enabled = 0 WHERE name = ?", (row["name"],))

    # Sweep (idempotent): drop unpublished items from sources no longer in config.
    # Unconditional sweep prevents BBC-article bug: disabled-earlier feeds kept
    # articles.
    if wanted:
        placeholders = ",".join("?" for _ in wanted)
        dropped = conn().execute(
            f"""
            UPDATE items
               SET status = 'expired',
                   status_reason = 'source no longer in config',
                   updated_at = ?
             WHERE origin = 'rss'
               AND status IN ('queued', 'written')
               AND source_name NOT IN ({placeholders})
            """,
            (now_iso(), *sorted(wanted)),
        ).rowcount
        if dropped:
            logger.info("Dropped %d unpublished item(s) from source(s) no longer "
                        "in config", dropped)

    conn().commit()


def drop_unfollowed_x_items(handles: Iterable[str]) -> int:
    """Delete queued tweets from unfollowed X accounts to prevent delayed posts."""
    followed = set(handles)
    rows = conn().execute(
        "SELECT DISTINCT source_name FROM items "
        "WHERE origin = 'x' AND status IN ('queued', 'written')"
    )
    stale = [r["source_name"] for r in rows if r["source_name"] not in followed]
    if not stale:
        return 0

    placeholders = ",".join("?" for _ in stale)
    dropped = conn().execute(
        f"""
        UPDATE items
           SET status = 'expired',
               status_reason = 'X account no longer followed',
               updated_at = ?
         WHERE origin = 'x'
           AND status IN ('queued', 'written')
           AND source_name IN ({placeholders})
        """,
        (now_iso(), *stale),
    ).rowcount
    conn().commit()

    if dropped:
        logger.info("Dropped %d queued tweet(s) from unfollowed account(s): %s",
                    dropped, ", ".join(sorted(stale)))
    return dropped


def get_enabled_sources() -> list[sqlite3.Row]:
    """Return every feed we should currently be polling."""
    return list(conn().execute("SELECT * FROM sources WHERE enabled = 1 ORDER BY name"))


def record_source_success(name: str, etag: str, last_modified: str) -> None:
    """Mark a feed as polled successfully, saving its caching tokens for next time."""
    conn().execute(
        """
        UPDATE sources
           SET etag = ?, last_modified = ?, last_checked_at = ?, last_ok_at = ?,
               fail_count = 0, last_error = ''
         WHERE name = ?
        """,
        (etag, last_modified, now_iso(), now_iso(), name),
    )
    conn().commit()


def record_source_failure(name: str, error: str) -> int:
    """Record a failed poll and return how many times it has now failed in a row."""
    conn().execute(
        """
        UPDATE sources
           SET last_checked_at = ?, fail_count = fail_count + 1, last_error = ?
         WHERE name = ?
        """,
        (now_iso(), error[:500], name),
    )
    conn().commit()
    row = conn().execute("SELECT fail_count FROM sources WHERE name = ?", (name,)).fetchone()
    return row["fail_count"] if row else 0


# ITEMS

def _calendar_key(match: dict | None) -> str:
    """The scheduled release an item belongs to, as a name that survives a feed
    refresh. Duplicated from nodes/calendar.key_for to keep utils/ free of a
    nodes/ import."""
    if not match:
        return ""
    return f"{match.get('country','')}|{match.get('title','')}|{match.get('at_utc','')}"


def insert_item(
    *,
    origin: str,
    source_name: str,
    external_id: str,
    url: str = "",
    title: str = "",
    body: str = "",
    image_url: str = "",
    video_url: str = "",
    video_kind: str = "",
    calendar: dict | None = None,
    published_at: str | None = None,
    norm_title: str = "",
    title_hash: str = "",
    topic_hint: str = "",
    status: str = "queued",
    status_reason: str = "",
    link_url: str = "",
) -> int | None:
    """Store item; return its id or None if already exists (duplicate check 1)."""
    try:
        cursor = conn().execute(
            """
            INSERT INTO items (
                origin, source_name, external_id, url, title, body, image_url,
                video_url, video_kind,
                calendar_title, calendar_forecast, calendar_previous, calendar_key,
                published_at, norm_title, title_hash, topic_hint,
                status, status_reason, fetched_at, updated_at, link_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                origin, source_name, external_id, url, title,
                body[: config.MAX_BODY_CHARS], image_url, video_url, video_kind,
                (calendar or {}).get("title", ""), (calendar or {}).get("forecast", ""),
                (calendar or {}).get("previous", ""), _calendar_key(calendar),
                published_at,
                norm_title, title_hash, topic_hint,
                status, status_reason, now_iso(), now_iso(), link_url,
            ),
        )
        conn().commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        # UNIQUE rule hit: duplicate. Rollback critical: failed writes hold lock causing
        # "database is locked"—especially dashboard force-post.
        conn().rollback()
        return None


def item_seen(origin: str, external_id: str) -> bool:
    """True if this address is already stored, whatever happened to it."""
    return conn().execute("SELECT 1 FROM items WHERE origin = ? AND external_id = ?",
                          (origin, external_id)).fetchone() is not None


def title_hash_seen(title_hash: str, hours: int) -> sqlite3.Row | None:
    """Check 2: return earlier item with same headline fingerprint (catches syndication)."""
    if not title_hash:
        return None
    return conn().execute(
        f"""
        SELECT id, title, source_name FROM items
         WHERE title_hash = ?
           AND fetched_at > datetime('now', '-{int(hours)} hours')
         ORDER BY id LIMIT 1
        """,
        (title_hash,),
    ).fetchone()


def recent_titles(hours: int, exclude_item_id: int | None = None) -> list[tuple[int, str]]:
    """Check 3: (id, normalised headline) for items seen recently."""
    rows = conn().execute(
        f"""
        SELECT id, norm_title FROM items
         WHERE norm_title != ''
           AND fetched_at > datetime('now', '-{int(hours)} hours')
           AND id != ?
        """,
        (exclude_item_id or -1,),
    )
    return [(row["id"], row["norm_title"]) for row in rows]


def recent_embeddings(
    hours: int,
    exclude_item_id: int | None = None,
    *,
    near_time: str | None = None,
    max_gap_hours: int | None = None,
) -> list[tuple[int, bytes]]:
    """Check 4: return (id, embedding) for recently understood items. TIME GATE blocks
    recurring reports (daily flows, weekly roundups).
    """
    where = [
        "embedding IS NOT NULL",
        f"fetched_at > datetime('now', '-{int(hours)} hours')",
        "id != ?",
    ]
    params: list = [exclude_item_id or -1]

    if near_time and max_gap_hours is not None:
        where.append(
            "abs(julianday(fetched_at) - julianday(?)) * 24.0 <= ?"
        )
        params += [near_time, float(max_gap_hours)]

    rows = conn().execute(
        f"SELECT id, embedding FROM items WHERE {' AND '.join(where)}",
        tuple(params),
    )
    return [(row["id"], row["embedding"]) for row in rows]


def set_item_embedding(item_id: int, blob: bytes) -> None:
    """Save an item's meaning-vector so future items can be compared against it."""
    conn().execute("UPDATE items SET embedding = ? WHERE id = ?", (blob, item_id))
    conn().commit()


def force_item(item_id: int, *, was_status: str, was_reason: str, note: str = "") -> None:
    """Restore rejected item to queue; log override for testing prompt changes."""
    connection = conn()
    with connection:
        connection.execute(
            """INSERT INTO overrides (item_id, was_status, was_reason, decision, note, created_at)
               VALUES (?, ?, ?, 'publish', ?, datetime('now'))""",
            (item_id, was_status, was_reason, note),
        )
        connection.execute(
            """UPDATE items SET status = 'queued', status_reason = 'forced by a human',
                                forced = 1, attempts = 0, story_id = NULL
                WHERE id = ?""",
            (item_id,),
        )


def unpublish_note(item_id: int, *, note: str = "") -> None:
    """Log that published post should not have gone out (label only, not deletion)."""
    row = get_item(item_id)
    connection = conn()
    with connection:
        connection.execute(
            """INSERT INTO overrides (item_id, was_status, was_reason, decision, note, created_at)
               VALUES (?, ?, ?, 'should_not_have_posted', ?, datetime('now'))""",
            (item_id, row["status"] if row else "", row["status_reason"] if row else "", note),
        )


def recent_overrides(limit: int = 100) -> list[sqlite3.Row]:
    """Every time a human disagreed with the pipeline, newest first."""
    return list(conn().execute(
        """SELECT o.*, i.title, i.source_name, i.topic, i.market, i.importance
             FROM overrides o JOIN items i ON i.id = o.item_id
            ORDER BY o.id DESC LIMIT ?""",
        (limit,),
    ))


def recent_published_posts(hours: int, limit: int) -> list[sqlite3.Row]:
    """What the channel actually sent recently, newest first — see nodes/echo.py."""
    return list(conn().execute(
        """SELECT p.post_html, p.sent_at
             FROM posts p
            WHERE p.status = 'sent' AND p.telegram_message_id IS NOT NULL
              AND p.sent_at > datetime('now', ?)
            ORDER BY p.sent_at DESC LIMIT ?""",
        (f"-{int(hours)} hours", int(limit)),
    ))


def add_item_media(item_id: int, *, images: list[str] = (),
                   videos: list[dict] = ()) -> None:
    """Add candidate images and videos to an item, keeping order and dropping repeats."""
    import json
    row = conn().execute("SELECT media_json FROM items WHERE id = ?", (item_id,)).fetchone()
    try:
        current = json.loads(row["media_json"]) if row and row["media_json"] else {}
    except ValueError:
        current = {}
    have_images = current.get("images", [])
    have_videos = current.get("videos", [])
    have_images += [u for u in images if u and u not in have_images]
    known = {v["url"] for v in have_videos}
    have_videos += [v for v in videos if v.get("url") and v["url"] not in known]
    conn().execute("UPDATE items SET media_json = ? WHERE id = ?",
                   (json.dumps({"images": have_images, "videos": have_videos}), item_id))
    conn().commit()


def set_post_media(post_id: int, **fields) -> None:
    """Record what the analysts chose for a post. Marks the post as checked."""
    allowed = {"media_image_url", "media_video_url", "media_video_kind", "media_note"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn().execute(
        f"UPDATE posts SET media_checked = 1{', ' + sets if sets else ''} WHERE id = ?",
        (*fields.values(), post_id),
    )
    conn().commit()


def get_post_media(post_id: int) -> sqlite3.Row | None:
    """The media the analysts chose for a post, or None if the post does not exist."""
    return conn().execute(
        "SELECT media_checked, media_image_url, media_video_url, media_video_kind, media_note "
        "FROM posts WHERE id = ?", (post_id,),
    ).fetchone()


def set_item_link(item_id: int, link_url: str) -> None:
    """Record the link to the thing itself, found on an aggregator's page."""
    conn().execute("UPDATE items SET link_url = ? WHERE id = ?", (link_url, item_id))
    conn().commit()


def set_article_text(item_id: int, text: str) -> None:
    """Keep the article we read for this item, so its URL is never fetched twice."""
    conn().execute("UPDATE items SET article_text = ? WHERE id = ?", (text, item_id))
    conn().commit()


def set_item_status(item_id: int, status: str, reason: str = "") -> None:
    """Move item to new stage and record why; unexplained vanished items are design
    failures.
    """
    conn().execute(
        "UPDATE items SET status = ?, status_reason = ?, updated_at = ? WHERE id = ?",
        (status, reason[:500], now_iso(), item_id),
    )
    conn().commit()


def set_item_sorting(item_id: int, topic: str, importance: int,
                     market: str, reason: str = "") -> None:
    """Store what the sorter decided, including WHY.

    The reason used to be kept only for items the sorter rejected, written into
    status_reason. An item that passed carried it in memory and lost it: by the
    time the post went out, status_reason had been overwritten with "sent as
    message 531", so nothing recorded why the channel judged it worth covering.
    """
    conn().execute(
        "UPDATE items SET topic = ?, importance = ?, market = ?, sorter_reason = ?, "
        "updated_at = ? WHERE id = ?",
        (topic, importance, market, reason[:300], now_iso(), item_id),
    )
    conn().commit()


def bump_attempts(item_id: int) -> int:
    """Count one more failed try on an item and return the new total."""
    conn().execute(
        "UPDATE items SET attempts = attempts + 1, updated_at = ? WHERE id = ?",
        (now_iso(), item_id),
    )
    conn().commit()
    row = conn().execute("SELECT attempts FROM items WHERE id = ?", (item_id,)).fetchone()
    return row["attempts"] if row else 0


def get_item(item_id: int) -> sqlite3.Row | None:
    """Fetch one item by id."""
    return conn().execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()


def next_queued_items(limit: int) -> list[sqlite3.Row]:
    """Return queued items ordered by importance then recency (old "breaking" stories go
    stale).
    """
    return list(conn().execute(
        """
        SELECT * FROM items
         WHERE status = 'queued' AND attempts < ?
         ORDER BY importance DESC, id DESC
         LIMIT ?
        """,
        (config.MAX_ATTEMPTS, limit),
    ))


def expire_stale_items(ttl_minutes: int) -> int:
    """Bin queued items older than ttl_minutes (forced items exempt); clock runs from
    arrival, not queueing.
    """
    cursor = conn().execute(
        f"""
        UPDATE items
           SET status = 'expired',
               status_reason = 'sat in the queue longer than {int(ttl_minutes)} minutes',
               updated_at = ?
         WHERE status = 'queued'
           AND COALESCE(forced, 0) = 0
           AND fetched_at < datetime('now', '-{int(ttl_minutes)} minutes')
        """,
        (now_iso(),),
    )
    conn().commit()
    return cursor.rowcount


def trim_queue(max_size: int) -> int:
    """Bin oldest/least-important items if queue exceeds max_size (second safety net after
    TTL).
    """
    total = conn().execute(
        "SELECT COUNT(*) AS n FROM items WHERE status = 'queued'"
    ).fetchone()["n"]
    if total <= max_size:
        return 0

    cursor = conn().execute(
        """
        UPDATE items
           SET status = 'expired', status_reason = 'queue over size limit', updated_at = ?
         WHERE id IN (
             SELECT id FROM items
              WHERE status = 'queued'
              ORDER BY importance ASC, id ASC
              LIMIT ?
         )
        """,
        (now_iso(), total - max_size),
    )
    conn().commit()
    return cursor.rowcount


def recent_low_impact(limit: int, market: str = "") -> list[sqlite3.Row]:
    """Return items importance gate dropped (status=low_impact). Pass market name to
    filter; 'none' shows stories with no market impact.
    """
    sql = """
        SELECT id, source_name, title, topic, market, importance,
               status_reason, updated_at
          FROM items
         WHERE status = 'low_impact'
    """
    params: list[Any] = []
    if market:
        sql += " AND market = ?"
        params.append(market)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return list(conn().execute(sql, tuple(params)))


def market_breakdown(days: int) -> list[sqlite3.Row]:
    """Count published vs. seen items by market (shows where gate spends 'none' verdicts)."""
    return list(conn().execute(
        f"""
        SELECT market,
               COUNT(*) AS seen,
               SUM(CASE WHEN status = 'published' THEN 1 ELSE 0 END) AS published
          FROM items
         WHERE market != ''
           AND updated_at > datetime('now', '-{int(days)} days')
         GROUP BY market
         ORDER BY seen DESC
        """
    ))


# DUPLICATE AUDIT TRAIL

def log_dedup_hit(
    *, item_id: int, matched_item_id: int | None, rung: str,
    score: float, kept: bool, detail: str,
) -> None:
    """Log similarity hits; called for drops and near-misses; never raises (this is
    evidence, not decision).
    """
    try:
        _log_dedup_hit(item_id, matched_item_id, rung, score, kept, detail)
    except sqlite3.OperationalError as error:
        logger.warning("Dedup evidence for item %s not recorded: %s", item_id, error)


def _log_dedup_hit(item_id, matched_item_id, rung, score, kept, detail) -> None:
    conn().execute(
        """
        INSERT INTO dedup_hits (item_id, matched_item_id, rung, score, kept, detail, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (item_id, matched_item_id, rung, score, 1 if kept else 0, detail[:1000], now_iso()),
    )
    conn().commit()


# POSTS

def create_post(
    *, item_id: int, topic: str, post_html: str, image_url: str,
    writer_model: str, source_context: dict | None = None,
) -> int | None:
    """Store post, return its id or None if already exists (prevents duplicate sends on
    crash).
    """
    try:
        cursor = conn().execute(
            """
            INSERT INTO posts (
                item_id, topic, post_html, image_url, has_image,
                char_count, writer_model, status, created_at, source_context
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)
            """,
            (
                item_id, topic, post_html, image_url, 1 if image_url else 0,
                len(post_html), writer_model, now_iso(),
                json.dumps(source_context or {}, ensure_ascii=False),
            ),
        )
        conn().commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        conn().rollback()   # same reason as insert_item: a failed write holds the lock
        return None


def get_post_by_item(item_id: int) -> sqlite3.Row | None:
    """Fetch the post belonging to an item, if one has been written."""
    return conn().execute("SELECT * FROM posts WHERE item_id = ?", (item_id,)).fetchone()


def set_post_status(post_id: int, status: str) -> None:
    """Move a post to a new stage: draft → approved/declined → sent."""
    conn().execute("UPDATE posts SET status = ? WHERE id = ?", (status, post_id))
    conn().commit()


def update_post_text(post_id: int, post_html: str) -> None:
    """Replace post text (rewrite loop). Rejected drafts kept in editor_decisions, not
    here.
    """
    conn().execute(
        "UPDATE posts SET post_html = ?, char_count = ?, status = 'draft' WHERE id = ?",
        (post_html, len(post_html), post_id),
    )
    conn().commit()


def mark_post_sent(post_id: int, message_id: int, post_url: str) -> None:
    """Record that a post reached the channel, and where it landed."""
    conn().execute(
        """
        UPDATE posts
           SET status = 'sent', telegram_message_id = ?, post_url = ?, sent_at = ?
         WHERE id = ?
        """,
        (message_id, post_url, now_iso(), post_id),
    )
    conn().commit()


def mark_message_deleted(message_id: int) -> int | None:
    """Record that a channel message was deleted by hand. Returns its story id.

    Every story query reads only 'sent' posts, so this takes the post out of
    its story: later posts stop replying to it and the models stop seeing it as
    something the channel said. The story's summary falls back to its newest
    remaining post, or to its headline if none is left.
    """
    row = conn().execute(
        """
        SELECT p.id, p.item_id, i.story_id FROM posts p JOIN items i ON i.id = p.item_id
         WHERE p.telegram_message_id = ? AND p.status = 'sent'
        """,
        (message_id,),
    ).fetchone()
    if row is None:
        return None

    conn().execute("UPDATE posts SET status = 'deleted' WHERE id = ?", (row["id"],))
    conn().execute(
        "UPDATE items SET status_reason = ?, updated_at = ? WHERE id = ?",
        (f"message {message_id} was deleted from the channel", now_iso(), row["item_id"]),
    )
    if row["story_id"]:
        newest = conn().execute(
            """
            SELECT p.post_html, p.sent_at FROM posts p JOIN items i ON i.id = p.item_id
             WHERE i.story_id = ? AND p.status = 'sent'
             ORDER BY p.sent_at DESC, p.id DESC LIMIT 1
            """,
            (row["story_id"],),
        ).fetchone()
        if newest:
            from brain import persona_loader
            conn().execute(
                "UPDATE stories SET summary = ?, last_post_at = ? WHERE id = ?",
                (persona_loader.visible_text(newest["post_html"])[:300],
                 newest["sent_at"], row["story_id"]),
            )
        else:
            conn().execute(
                "UPDATE stories SET summary = headline, last_post_at = NULL WHERE id = ?",
                (row["story_id"],),
            )
    conn().commit()
    return row["story_id"]


def get_recent_sent_posts(limit: int) -> list[sqlite3.Row]:
    """Return recent sent posts (newest first) for persona memory; only visible text."""
    return list(conn().execute(
        "SELECT id, post_html, sent_at FROM posts "
        "WHERE status = 'sent' AND post_html != '' "
        "ORDER BY sent_at DESC, id DESC LIMIT ?",
        (limit,),
    ))


def bump_send_attempts(post_id: int) -> int:
    """Count one more failed send attempt and return the new total."""
    conn().execute("UPDATE posts SET send_attempts = send_attempts + 1 WHERE id = ?", (post_id,))
    conn().commit()
    row = conn().execute("SELECT send_attempts FROM posts WHERE id = ?", (post_id,)).fetchone()
    return row["send_attempts"] if row else 0


def posts_sent_since(minutes: int) -> int:
    """How many posts we have sent in the last N minutes — powers the rate caps."""
    return conn().execute(
        f"""
        SELECT COUNT(*) AS n FROM posts
         WHERE status = 'sent' AND sent_at > datetime('now', '-{int(minutes)} minutes')
        """
    ).fetchone()["n"]


def seconds_since_last_post() -> float:
    """How long since the last message went out. Large number if we never have."""
    row = conn().execute(
        "SELECT MAX(sent_at) AS last FROM posts WHERE status = 'sent'"
    ).fetchone()
    if not row or not row["last"]:
        return 1e9
    last = datetime.strptime(row["last"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last).total_seconds()


# STORIES: unit of work; items join stories, stories post when moved. All state rebuilt
# from queries.

def story_of_item(item_id: int) -> sqlite3.Row | None:
    """The story an item belongs to, or None when it was never placed."""
    return conn().execute(
        "SELECT s.* FROM stories s JOIN items i ON i.story_id = s.id WHERE i.id = ?",
        (item_id,),
    ).fetchone()


def story_for_calendar_key(key: str) -> sqlite3.Row | None:
    """The live story that IS this scheduled release, if one is already open.

    One release, one story, decided without a model. Placement used to ask a
    model which open story a data print joined, and on 30 September it put the
    month's PCE figure into a story about Fed officials talking about rate hikes.
    """
    if not key:
        return None
    return conn().execute(
        "SELECT * FROM stories WHERE calendar_key = ? AND status = 'live' "
        "ORDER BY id DESC LIMIT 1",
        (key,),
    ).fetchone()


def create_story(*, headline: str, summary: str, item_id: int, at: str,
                 calendar_key: str = "") -> int:
    """Create story and attach first item (single transaction); crash between risks empty
    story.
    """
    cursor = conn().execute(
        "INSERT INTO stories (headline, summary, first_at, last_item_at, calendar_key) "
        "VALUES (?, ?, ?, ?, ?)",
        (headline[:200], summary[:300], at, at, calendar_key),
    )
    story_id = int(cursor.lastrowid)
    conn().execute(
        "UPDATE items SET story_id = ?, updated_at = ? WHERE id = ?",
        (story_id, at, item_id),
    )
    conn().commit()
    return story_id


def attach_item_to_story(item_id: int, story_id: int) -> None:
    """Put an existing item into an existing story."""
    at = now_iso()
    conn().execute(
        "UPDATE items SET story_id = ?, updated_at = ? WHERE id = ?",
        (story_id, at, item_id),
    )
    conn().execute(
        "UPDATE stories SET last_item_at = ? WHERE id = ?", (at, story_id),
    )
    conn().commit()


def detach_item_from_story(item_id: int) -> None:
    """Take an item back out. Only the gate's "this does not belong here" uses it."""
    conn().execute(
        "UPDATE items SET story_id = NULL, updated_at = ? WHERE id = ?",
        (now_iso(), item_id),
    )
    conn().commit()


def get_story(story_id: int) -> sqlite3.Row | None:
    """One story row, or None."""
    return conn().execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()


def load_live_stories(idle_hours: int, limit: int) -> list[sqlite3.Row]:
    """Open stories a new item could still join, most recently active first."""
    return list(conn().execute(
        f"""
        SELECT * FROM stories
         WHERE status = 'live'
           AND last_item_at > datetime('now', '-{int(idle_hours)} hours')
         ORDER BY last_item_at DESC
         LIMIT ?
        """,
        (limit,),
    ))


def get_story_items(story_id: int) -> list[sqlite3.Row]:
    """Every item in a story, oldest first. The caller splits them on status."""
    return list(conn().execute(
        "SELECT * FROM items WHERE story_id = ? ORDER BY id ASC", (story_id,),
    ))


def get_story_posts(story_id: int) -> list[sqlite3.Row]:
    """What the channel has already published on a story, oldest first."""
    return list(conn().execute(
        """
        SELECT p.id, p.post_html, p.sent_at, p.telegram_message_id, p.item_id
          FROM posts p JOIN items i ON i.id = p.item_id
         WHERE i.story_id = ? AND p.status = 'sent'
         ORDER BY p.sent_at ASC, p.id ASC
        """,
        (story_id,),
    ))


def set_story_name(story_id: int, name: str) -> None:
    """Give a story its short human name — see nodes/stories.py."""
    conn().execute("UPDATE stories SET name = ? WHERE id = ?", (name[:90], story_id))
    conn().commit()


def record_story_post(story_id: int, published_item_id: int, post_text: str,
                      *, covers_others: bool = True) -> None:
    """Log a story's post and mark only the items it actually covered.

    `post_text` is the published post as the reader sees it. Every item waiting on
    the story fed the writer, but the writer does not have to use them all, so
    nodes/coverage.py checks each one against the post: an item is marked merged
    only when the post repeats a detail that item alone supplied. The rest go back
    to held, where they stay as fuel for the story's next post instead of being
    silently buried. covers_others=False for a forced post, which was written from
    one item alone. Call only after the send succeeds; idempotent.
    """
    at = now_iso()
    conn().execute(
        "UPDATE stories SET last_post_at = ?, summary = ? WHERE id = ?",
        (at, post_text[:300], story_id),
    )
    if not covers_others:
        conn().commit()
        return

    waiting = list(conn().execute(
        """
        SELECT id, title, body FROM items
         WHERE story_id = ? AND status IN ('queued', 'held')
        """,
        (story_id,),
    ))

    # The trigger is the post's main source, so it must be part of the comparison
    # even though it is never a candidate.
    trigger = conn().execute(
        "SELECT id, title, body FROM items WHERE id = ?", (published_item_id,)
    ).fetchone()

    from nodes import coverage
    covered, still_waiting = coverage.split_by_coverage(post_text, waiting, trigger)

    for item_id, why in covered:
        conn().execute(
            "UPDATE items SET status = 'merged', status_reason = ?, updated_at = ? "
            " WHERE id = ?",
            (f"covered by the story {story_id} post from item {published_item_id} — {why}",
             at, item_id),
        )
    for item_id, why in still_waiting:
        conn().execute(
            "UPDATE items SET status = 'held', status_reason = ?, updated_at = ? "
            " WHERE id = ?",
            (f"story {story_id} posted from item {published_item_id} but {why}; "
             f"still waiting for the next one",
             at, item_id),
        )
    conn().commit()

    if covered:
        bump_counter("story_item_covered", len(covered))
    if still_waiting:
        bump_counter("story_item_left_waiting", len(still_waiting))
        logger.info("Story %s posted from item %s: %d item(s) covered, "
                    "%d left waiting because the post did not carry their details",
                    story_id, published_item_id, len(covered), len(still_waiting))


def close_stale_stories(idle_hours: int, max_hours: int) -> list[sqlite3.Row]:
    """Close idle/aged stories; return closed rows with waiting counts (unposted content
    is a design failure point).
    """
    doomed = list(conn().execute(
        f"""
        SELECT s.id, s.headline,
               (SELECT COUNT(*) FROM items i
                 WHERE i.story_id = s.id AND i.status IN ('queued', 'held')) AS waiting
          FROM stories s
         WHERE s.status = 'live'
           AND (s.last_item_at < datetime('now', '-{int(idle_hours)} hours')
                OR s.first_at  < datetime('now', '-{int(max_hours)} hours'))
        """
    ))
    if doomed:
        conn().executemany(
            "UPDATE stories SET status = 'closed' WHERE id = ?",
            [(row["id"],) for row in doomed],
        )
        conn().commit()
    return doomed


def stories_due_for_roundup(min_items: int, min_minutes: int,
                            max_quiet_hours: int) -> list[sqlite3.Row]:
    """Live stories with enough held items to ask the gate about a roundup.

    Each set of held items is asked about once. Without that, the sweep put the
    same question to the gate every round until it said yes: story 108 was held
    twice at 13:12 on 2026-10-01 and posted at 13:22 on the same three items.
    """
    return list(conn().execute(
        f"""
        SELECT s.id,
               (SELECT COUNT(*) FROM items i
                 WHERE i.story_id = s.id AND i.status = 'held') AS waiting,
               (SELECT MAX(i.id) FROM items i
                 WHERE i.story_id = s.id AND i.status = 'held') AS newest_held
          FROM stories s
         WHERE s.status = 'live'
           AND s.last_post_at IS NOT NULL
           AND s.last_post_at < datetime('now', '-{int(min_minutes)} minutes')
           AND s.last_post_at > datetime('now', '-{int(max_quiet_hours)} hours')
           AND waiting >= ?
           AND newest_held > COALESCE(s.roundup_asked_item_id, 0)
         ORDER BY s.last_post_at ASC
        """,
        (min_items,),
    ))


def mark_roundup_asked(story_id: int, item_id: int) -> None:
    """Remember that the gate has been asked about this story's held items up to item_id."""
    conn().execute("UPDATE stories SET roundup_asked_item_id = ? WHERE id = ?",
                   (item_id, story_id))
    conn().commit()


def newest_held_item(story_id: int) -> sqlite3.Row | None:
    """The item that carries a roundup through the graph: the story's latest held one."""
    return conn().execute(
        "SELECT * FROM items WHERE story_id = ? AND status = 'held' "
        "ORDER BY id DESC LIMIT 1",
        (story_id,),
    ).fetchone()


def replace_calendar(rows: list[tuple]) -> None:
    """Swap in this week's releases. One transaction, so a reader never sees half."""
    conn().execute("DELETE FROM calendar")
    conn().executemany(
        "INSERT OR IGNORE INTO calendar (country, title, at_utc, impact, forecast, previous) "
        "VALUES (?, ?, ?, ?, ?, ?)", rows,
    )
    conn().commit()


def calendar_between(since: str, until: str) -> list[sqlite3.Row]:
    """Scheduled releases in a window, for matching an item that just arrived."""
    return list(conn().execute(
        "SELECT * FROM calendar WHERE at_utc BETWEEN ? AND ? ORDER BY at_utc",
        (since, until),
    ))


def calendar_age_minutes() -> float | None:
    """How stale the stored calendar is, or None if there is none."""
    row = conn().execute("SELECT value FROM meta WHERE key = 'calendar_refreshed_at'").fetchone()
    if row is None:
        return None
    then = datetime.strptime(row["value"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() / 60


def recent_held(limit: int) -> list[sqlite3.Row]:
    """Return held items (newest first); counterpart to recent_low_impact(); see
    tools/stats.py --held.
    """
    return list(conn().execute(
        """
        SELECT i.id, i.source_name, i.title, i.story_id, i.status_reason,
               i.updated_at, s.headline AS story_headline
          FROM items i LEFT JOIN stories s ON s.id = i.story_id
         WHERE i.status = 'held'
         ORDER BY i.id DESC LIMIT ?
        """,
        (limit,),
    ))


# EDITOR AUDIT TRAIL

def log_editor_decision(
    *, post_id: int, item_id: int, verdict: str, rules_broken: list[str],
    reason: str, confidence: float, post_html: str, model: str,
    latency_ms: int, attempt: int = 1,
) -> None:
    """Log editor verdicts (approvals and rejections) for decline-rate calculation."""
    conn().execute(
        """
        INSERT INTO editor_decisions (
            post_id, item_id, verdict, rules_broken, reason, confidence,
            post_html, model, latency_ms, attempt, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            post_id, item_id, verdict, json.dumps(rules_broken), reason[:1000],
            confidence, post_html, model, latency_ms, attempt, now_iso(),
        ),
    )
    conn().commit()


def recent_decline_rate(window: int) -> tuple[float, int]:
    """Return (share_declined, count) for recent verdicts; alarm if editor rejects most
    posts.
    """
    rows = list(conn().execute(
        "SELECT verdict FROM editor_decisions ORDER BY id DESC LIMIT ?", (window,)
    ))
    if not rows:
        return 0.0, 0
    declines = sum(1 for r in rows if r["verdict"] == "decline")
    return declines / len(rows), len(rows)


# COUNTERS AND NOTES

def counters_today(prefix: str) -> dict[str, int]:
    """Return today's tallies matching prefix (never raises); turns scattered failures
    into rates.
    """
    try:
        rows = conn().execute(
            "SELECT kind, n FROM counters WHERE day = date('now') AND kind LIKE ?",
            (prefix + "%",))
        return {r["kind"]: r["n"] for r in rows}
    except sqlite3.OperationalError as error:
        logger.debug("Counters for %s not read: %s", prefix, error)
        return {}


def bump_counter(kind: str, n: int = 1) -> None:
    """Add to today's tally (never raises; losing count is better than losing news)."""
    try:
        _bump_counter(kind, n)
    except sqlite3.OperationalError as error:
        logger.debug("Counter %s not recorded: %s", kind, error)


def _bump_counter(kind: str, n: int) -> None:
    conn().execute(
        """
        INSERT INTO counters (day, kind, n) VALUES (?, ?, ?)
        ON CONFLICT(day, kind) DO UPDATE SET n = n + excluded.n
        """,
        (today_utc(), kind, n),
    )
    conn().commit()


def get_counters(day: str | None = None) -> dict[str, int]:
    """Return all of a day's tallies as a plain dictionary. Defaults to today."""
    rows = conn().execute(
        "SELECT kind, n FROM counters WHERE day = ?", (day or today_utc(),)
    )
    return {row["kind"]: row["n"] for row in rows}


def meta_get(key: str, default: str = "") -> str:
    """Read a one-off saved fact."""
    row = conn().execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def meta_set(key: str, value: str) -> None:
    """Save a one-off fact."""
    conn().execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    conn().commit()


def query(sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    """Run a SELECT and return the rows. Used by tools/stats.py for reporting."""
    return list(conn().execute(sql, params))
