"""Keeps the guides and skills that passed the sorter but hit their daily limit, and
posts the best one when the limit allows another.

They wait with status 'capped'. Each round, for every limited topic that may post
again, a model picks the most useful waiting item against the channel's rubric;
anything older than RESERVE_DAYS is dropped.
"""

from __future__ import annotations

import config
from pipeline import stations
from utils import db, logger as log_setup, openrouter

log = log_setup.get("reserve")

_MAX_COMPARED = 8

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["best", "reason"],
    "properties": {
        "best": {"type": "integer", "description": "Index of the most useful item, from 0."},
        "reason": {"type": "string", "description": "One short sentence."},
    },
}

PICK_PROMPT = """You choose which ONE of several waiting items this channel posts next.
They all passed the rules below already; the channel only has room for one of them now.
Pick the one most useful to the channel's reader today, by those same rules: the one a
freelancer, business owner, creator or student is most likely to try and keep using.
A well-known maker, a clearer benefit and a wider audience beat a niche one.

THE CHANNEL'S RULES:
"""


def _expire_old() -> int:
    cursor = db.conn().execute(
        f"""UPDATE items SET status = 'expired', updated_at = datetime('now'),
                  status_reason = 'waited {config.RESERVE_DAYS} days in the reserve without a free slot'
             WHERE status = 'capped'
               AND fetched_at < datetime('now', '-{int(config.RESERVE_DAYS)} days')""")
    db.conn().commit()
    return cursor.rowcount


def _waiting(topic: str) -> list:
    return db.conn().execute(
        """SELECT * FROM items WHERE status = 'capped' AND topic = ?
            ORDER BY importance DESC, fetched_at DESC LIMIT ?""",
        (topic, _MAX_COMPARED)).fetchall()


async def _pick(rows: list) -> int:
    """Index of the best row, by a model reading the rubric; the top-scored one if it fails."""
    if len(rows) == 1:
        return 0
    listing = "\n\n".join(
        f"[{i}] {row['title']}\nWhy it passed: {row['sorter_reason'] or ''}\n"
        f"{((row['article_text'] or row['body'] or '')[:400]).strip()}"
        for i, row in enumerate(rows))
    try:
        answer = await openrouter.chat_json(
            model=config.SORTER_MODEL, system=PICK_PROMPT + config.RUBRIC_PATH.read_text(),
            user=f"The waiting items:\n\n{listing}", schema=SCHEMA, schema_name="reserve_pick",
            temperature=0.0, max_tokens=300)
        best = int(answer.get("best", 0))
        if 0 <= best < len(rows):
            log.info("Reserve picked %r: %s", rows[best]["title"][:60], str(answer.get("reason"))[:120])
            return best
    except Exception as error:  # noqa: BLE001 - the highest score is a fine fallback
        log.warning("Reserve pick failed (%s) — taking the highest score", error)
    return 0


async def next_release():
    """The waiting item to post now, or None. Drops the ones that waited too long."""
    dropped = _expire_old()
    if dropped:
        log.info("Dropped %d reserve item(s) older than %d days", dropped, config.RESERVE_DAYS)
    for topic in config.TOPIC_LIMITS:
        if stations.topic_limit_reason(topic):
            continue
        rows = _waiting(topic)
        if rows:
            return rows[await _pick(rows)]
    return None
