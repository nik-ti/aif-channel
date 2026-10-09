"""One company, at most COMPANY_DAILY_LIMIT posts a UTC day; the rest go out together in the evening.

The company_limit station holds a company's extra items as 'waiting_digest'. Once a day,
from DIGEST_HOUR_UTC, each company's waiting items become ONE post with a bullet per item
(a lone waiting item is posted normally). A 5/5 item and the "other" company are never held.
All of it is counting labels in code; no model decides the grouping.
"""

from __future__ import annotations

from datetime import datetime, timezone

import config
from nodes import media, publisher
from utils import db, logger as log_setup

log = log_setup.get("digest")


def limit_reason(company: str, importance: int) -> str:
    """Why this item must wait for its company's digest, or "" if it may post now."""
    if not company or company == "other" or importance >= 5:
        return ""
    count = db.company_posts_today(company)
    if count < config.COMPANY_DAILY_LIMIT:
        return ""
    return (f"{company} already had {count} posts today (limit {config.COMPANY_DAILY_LIMIT}); "
            f"waiting for the {config.DIGEST_HOUR_UTC}:00 UTC digest")


def brief(company: str, count: int) -> str:
    """What the writer is told about a digest, on top of its usual rules."""
    return (
        f"COMPANY DIGEST. This post is the channel's own end-of-day roundup of {count} separate "
        f"announcements from {company} today. Each one is new to the reader. Write ONE post: a "
        f"bold first line such as \"More from {company} today\", then one • line per item, in the "
        f"order given, each saying in one sentence what it is and what it does for the reader. "
        f"Include every item, give each its own line, and add no link line. The rule about "
        f"picking one item from a roundup does not apply: that is for roundups written by others."
    )


def build_source(company: str, rows: list) -> dict:
    """The waiting items folded into one source for the writer, newest item as the carrier."""
    budget = 3600 // max(1, len(rows))
    parts = []
    for number, row in enumerate(rows, start=1):
        text = ((row["article_text"] or "").strip() or (row["body"] or "").strip())[:budget]
        parts.append(f"ITEM {number} [{row['source_name']}] {row['title'] or ''}\n{text}".strip())
    newest = rows[-1]
    return {
        "id": newest["id"], "source_name": newest["source_name"], "origin": newest["origin"],
        # No address: a digest of several things has no one page to link to.
        "url": "", "link_url": "",
        "title": f"More from {company} today",
        "body": "\n\n".join(parts),
        "source_items": [{"id": r["id"], "source_name": r["source_name"], "url": r["url"]}
                         for r in rows],
        "candidate_media": media.merge(rows),
        "image_url": "", "video_url": "", "video_kind": "",
        "topic": "digest", "topic_hint": "", "company": company,
        "importance": max((r["importance"] or 0) for r in rows),
    }


def mark_covered(item_ids: list[int], carrier_id: int) -> None:
    """After a digest is sent: every item in it except the carrier counts as covered."""
    for item_id in item_ids:
        if item_id != carrier_id:
            db.set_item_status(item_id, "merged", f"in the company digest sent with item {carrier_id}")


async def run_due(now: datetime | None = None) -> dict[str, int]:
    """Send today's digests if it is time. Each company's runs at most once a UTC day."""
    from pipeline import graph

    now = now or datetime.now(timezone.utc)
    expired = db.expire_digest_waits(config.DIGEST_MAX_WAIT_HOURS)
    if expired:
        log.info("Dropped %d item(s) that waited too long for a digest", expired)
    if now.hour < config.DIGEST_HOUR_UTC:
        return {}

    by_company: dict[str, list] = {}
    for row in db.waiting_for_digest():
        by_company.setdefault(row["company"] or "other", []).append(row)

    outcomes: dict[str, int] = {}
    for company, rows in by_company.items():
        key = f"digest:{company}:{now:%Y-%m-%d}"
        if db.meta_get(key):
            continue
        allowed, why_not = publisher.check_limits()
        if not allowed:
            log.info("Digests wait for the next round: %s", why_not)
            break
        # Marked before it runs, so a crash halfway cannot send a second digest today.
        db.meta_set(key, now.isoformat())
        best = sorted(rows, key=lambda r: (r["importance"] or 0, r["id"]))[-config.DIGEST_MAX_ITEMS:]
        chosen = sorted(best, key=lambda r: r["id"])
        chosen_ids = {r["id"] for r in chosen}
        for row in rows:
            if row["id"] not in chosen_ids:
                db.set_item_status(row["id"], "expired",
                                   f"the {company} digest had room for {config.DIGEST_MAX_ITEMS}")
        try:
            if len(chosen) == 1:
                log.info("Digest time: %s has one waiting item, posted on its own", company)
                state = await graph.run_item(chosen[0], released=True)
            else:
                log.info("Digest time: %d %s items in one post", len(chosen), company)
                state = await graph.run_item(
                    build_source(company, chosen), digest=True,
                    digest_item_ids=[r["id"] for r in chosen], brief=brief(company, len(chosen)))
            outcome = state.get("outcome", "failed")
        except Exception as error:  # noqa: BLE001 - one company's digest must not stop the rest
            log.exception("The %s digest blew up: %s", company, error)
            outcome = "error"
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    return outcomes
