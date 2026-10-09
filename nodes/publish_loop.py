"""Turns queued items into posts at a sensible pace. Each tick expires stale items
and runs the rest through pipeline/graph.py.

Expiry is not optional. Without it the queue grows without limit and the channel
posts overnight news at breakfast.

Every step is written to the database, so a crash resumes where it stopped and
nothing is left half-posted.
"""

from __future__ import annotations

import asyncio

import config
from pipeline import graph, stations
from nodes import publisher
from utils import db, logger as log_setup

log = log_setup.get("publish")


def _expire_stale() -> None:
    """Drop queued items that have waited too long, and end stories that are over."""
    expired = db.expire_stale_items(config.QUEUE_TTL_MINUTES)
    db.prune_memory_embeddings()
    trimmed = db.trim_queue(config.MAX_QUEUE_SIZE)

    stale_stories = (db.close_stale_stories(config.STORY_IDLE_HOURS, config.STORY_MAX_HOURS)
                     if config.STORIES else [])
    for story in stale_stories:
        if story["waiting"]:
            # The one way this design can quietly drop something: a story that
            # went silent while still holding unposted items. Visible on purpose.
            log.info("Closed story %s with %d item(s) never covered: %s",
                     story["id"], story["waiting"], story["headline"][:70])
        else:
            log.info("Closed story %s: %s", story["id"], story["headline"][:70])

    if expired:
        log.info("Dropped %d item(s) that waited longer than %d minutes",
                 expired, config.QUEUE_TTL_MINUTES)
        db.bump_counter("expired", expired)
    if trimmed:
        log.info("Dropped %d item(s) because the queue was over %d",
                 trimmed, config.MAX_QUEUE_SIZE)
        db.bump_counter("expired", trimmed)


async def process_item(item, place_only: bool = False, sweep: bool = False) -> str:
    """Run one item through the graph.

    Returns one word: published | duplicate | irrelevant | low_impact | held |
    placed | declined | retry | failed.
    """
    item_id = item["id"]

    # A queued item with an already-approved post means a previous send failed.
    # That work is paid for, so go straight to sending.
    existing = db.get_post_by_item(item_id)
    if existing is not None and existing["status"] == "approved" and not place_only:
        checked = await stations.repeat_check_node({"item": dict(item), "post_id": existing["id"],
                                                     "post_html": existing["post_html"]})
        if checked.get("outcome"):
            return checked["outcome"]
        log.info("Item %s has an approved post — reader memory checked before retry", item_id)
        reply_to = None
        if item["story_id"]:
            earlier = db.get_story_posts(item["story_id"])
            if earlier:
                reply_to = earlier[0]["telegram_message_id"]
        sent = await publisher.execute(item, existing["post_html"], existing["id"],
                                       reply_to_message_id=reply_to)
        if sent and item["story_id"]:
            # Same booking the graph does. Without it a crash-then-resume sends
            # the post and leaves the story's other items held forever.
            from utils import persona_loader
            db.record_story_post(item["story_id"], item_id,
                                 persona_loader.visible_text(existing["post_html"]))
        return "published" if sent else "retry"

    # A human overruled a rejection from the dashboard; db.force_item set this
    # when it put the item back in the queue.
    forced = bool(item["forced"]) if "forced" in item.keys() else False
    state = await graph.run_item(item, dry_run=False, place_only=place_only,
                                 sweep=sweep, forced=forced)
    return state.get("outcome", "failed")


async def publish_once(limit: int | None = None) -> dict[str, int]:
    """Do one round: expire stale items, then process a few. Returns the tally."""
    _expire_stale()

    # Not being allowed to POST is not a reason to skip the round: forced items still go,
    # and with stories on, items are still filed. The rest wait queued.
    allowed, reason = publisher.check_limits()
    if not allowed:
        log.info("Not posting this round (%s)", reason)

    batch_size = limit or config.MAX_POSTS_PER_TICK
    outcomes: dict[str, int] = {}
    published = 0
    placed = 0

    # A guide or skill held back by its daily limit, now that the limit allows one.
    if allowed and config.TOPIC_LIMITS:
        from nodes import reserve
        waiting = await reserve.next_release()
        if waiting is not None:
            log.info("Releasing item %s from the reserve: %s", waiting["id"], waiting["title"][:70])
            state = await graph.run_item(waiting, dry_run=False, released=True)
            outcome = state.get("outcome", "failed")
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            if outcome == "published":
                published += 1
                await publisher.pause_between_sends()

    # A company's items held back by its daily limit, as one post in the evening.
    if allowed and not config.STORIES:
        from nodes import company_digest
        for outcome, count in (await company_digest.run_due()).items():
            outcomes[outcome] = outcomes.get(outcome, 0) + count

    # Look at more than we intend to publish; most get filtered out.
    # Selection is by importance; PROCESSING is chronological, because a story
    # built newest-first posts its ending and folds the beginning in afterwards.
    candidates = sorted(db.next_queued_items(batch_size * 8), key=lambda r: r["id"])
    if not candidates:
        return {}

    # One item at a time, deliberately: two placed concurrently would each see
    # the same open stories and each open one for the same news.
    for item in candidates:
        # A human pressed the button. The pacing cap is there to stop the
        # channel talking too much on its own; it is not a second opinion on a
        # decision somebody already made deliberately.
        forced = bool(item["forced"]) if "forced" in item.keys() else False

        # Re-asked per item, because the answer differs for a forced one.
        may_send, why_not = publisher.check_limits(forced=forced)

        if may_send and published >= batch_size:
            break
        if not may_send and not forced and not config.STORIES:
            continue        # nothing to file it into; it waits queued for a round that may post
        if not may_send and not forced and placed >= batch_size * 2:
            break

        try:
            outcome = await process_item(item, place_only=not may_send)
        except Exception as error:  # noqa: BLE001 - one bad item must not stop the rest
            log.exception("Item %s blew up: %s", item["id"], error)
            db.bump_attempts(item["id"])
            outcome = "error"

        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        if outcome == "placed":
            placed += 1

        if outcome == "published":
            published += 1
            if published < batch_size:
                await publisher.pause_between_sends()

            allowed, reason = publisher.check_limits()
            if not allowed:
                remaining = [c for c in candidates
                             if ("forced" in c.keys() and c["forced"])]
                if not remaining:
                    log.info("Stopping this round: %s", reason)
                    break
                log.info("%s — continuing for %d forced item(s)", reason, len(remaining))

    # Roundups. Held items only ever reach the gate when a NEW item arrives on
    # their story; a story that goes quiet would hold them forever. This sweep
    # asks the gate once more, after they have waited a while, whether together
    # they add up to something the reader has not been told.
    if config.STORIES and allowed and published < batch_size:
        for due in db.stories_due_for_roundup(config.STORY_DIGEST_ITEMS,
                                              config.STORY_DIGEST_MINUTES,
                                              config.STORY_DIGEST_MAX_QUIET_HOURS):
            carrier = db.newest_held_item(due["id"])
            if carrier is None:
                continue
            # Before asking, so a crash mid-roundup cannot turn into asking again.
            db.mark_roundup_asked(due["id"], carrier["id"])
            log.info("Story %s has %d item(s) waiting — asking the gate about a roundup",
                     due["id"], due["waiting"])
            try:
                outcome = await process_item(carrier, sweep=True)
            except Exception as error:  # noqa: BLE001
                log.exception("Roundup for story %s blew up: %s", due["id"], error)
                outcome = "error"
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            if outcome == "published":
                published += 1
                if published >= batch_size:
                    break
                await publisher.pause_between_sends()

    if outcomes:
        summary = ", ".join(f"{count} {name}" for name, count in sorted(outcomes.items()))
        log.info("Round finished: %s", summary)
    return outcomes


async def run(once: bool = False, limit: int | None = None) -> None:
    """Run the publishing loop. `once` does a single round and stops."""
    if once:
        log.info("Single publishing round...")
        await publish_once(limit=limit)
        return

    log.info("Publishing: checking every %ds, up to %d/hour",
             config.PUBLISH_TICK_SECONDS, config.MAX_POSTS_PER_HOUR)

    while True:
        try:
            await publish_once(limit=limit)
        except Exception as error:  # noqa: BLE001
            log.exception("Publishing round failed: %s", error)
            from utils import telegram_error
            telegram_error.send_error(str(error), node_name="publish_loop")

        await asyncio.sleep(config.PUBLISH_TICK_SECONDS)
