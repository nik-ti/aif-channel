"""Sends an approved post to the channel without changing a character of it.

A post with media goes out as ONE captioned message, which caps the text at 1024
characters instead of 4096. If the text will not fit, the media is dropped rather
than the words. If a video cannot be fetched, its thumbnail is used.
"""

from __future__ import annotations

import asyncio
import re

import config
from utils import db, logger as log_setup, telegram_client, telegram_html

log = log_setup.get("publisher")

# A tweet can contain anything, including a referral link aimed at our readers,
# so links pointing anywhere but the cited story are removed.
_LINK_TAG = re.compile(r'<a\s+href="([^"]*)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)


def _strip_foreign_links(html: str, allowed_url: str) -> str:
    """Remove links that did not come from us, keeping their visible text.

    The prompt and the editor also guard against this; only this layer does not
    depend on a model behaving.
    """
    if not html:
        return html

    allowed_host = ""
    match = re.match(r"https?://([^/]+)", allowed_url or "")
    if match:
        allowed_host = match.group(1).lower()

    def replace(link) -> str:
        href, text = link.group(1), link.group(2)
        host_match = re.match(r"https?://([^/]+)", href)
        host = host_match.group(1).lower() if host_match else ""
        if host and allowed_host and host == allowed_host:
            return link.group(0)          # our own source — keep it
        log.info("Removed a link the model added by itself: %s", href[:80])
        return text                        # keep the words, drop the link

    return _LINK_TAG.sub(replace, html)


def compose(post_html: str, url: str) -> str:
    """The post as it goes out: the writer's text, with any foreign link removed.

    No source credit. The channel speaks in its own voice, and a byline under
    every post read as a wire feed rather than a person. The source URL is
    still used here — to decide which links are ours — and stays on the item
    row for anyone who needs to trace a post back.
    """
    return _strip_foreign_links(post_html.strip(), url)


def check_limits(*, forced: bool = False) -> tuple[bool, str]:
    """Returns (allowed, why not). A minimum gap, an hourly cap, a daily cap.

    A forced item ignores the two caps: they exist to stop the channel talking
    too much on its own, and a human pressing the button has already decided
    this one is worth saying. It still waits out the gap, which is a different
    thing — that one keeps two posts from landing on top of each other, and
    Telegram cares about it whoever asked for the post.
    """
    gap = db.seconds_since_last_post()
    if gap < config.MIN_SECONDS_BETWEEN_POSTS:
        return False, (f"only {gap:.0f}s since the last post "
                       f"(minimum {config.MIN_SECONDS_BETWEEN_POSTS}s)")

    if forced:
        return True, ""

    this_hour = db.posts_sent_since(60)
    if this_hour >= config.MAX_POSTS_PER_HOUR:
        return False, f"already posted {this_hour} times this hour (limit {config.MAX_POSTS_PER_HOUR})"

    today = db.posts_sent_since(60 * 24)
    if today >= config.MAX_POSTS_PER_DAY:
        return False, f"already posted {today} times today (limit {config.MAX_POSTS_PER_DAY})"

    return True, ""


def _reply_target_gone(error: Exception) -> bool:
    """True if Telegram refused because the message we reply to no longer exists."""
    return "message to be replied not found" in str(error).lower()


async def _deliver(post_id: int, message: str, image_url: str, video_url: str,
                   video_kind: str, reply_to_message_id: int | None) -> int:
    """Send the post with the best media that works. Returns the message number."""
    message_id = None

    # Clip first, then its thumbnail, then plain text. Each step down is a
    # smaller loss than losing the post, which is why none of them raises.
    if (video_url or image_url) and telegram_html.would_cut_mid_sentence(
            message, telegram_html.CAPTION_LIMIT):
        # A complete post without a picture beats a truncated one with.
        log.info("Post %s is too long to caption media — sending as text instead",
                 post_id)
        db.bump_counter("image_dropped_too_long")
        video_url = image_url = ""

    if video_url:
        try:
            message_id = await telegram_client.send_clip(
                video_url, video_kind, message,
                reply_to_message_id=reply_to_message_id,
            )
        except Exception as error:  # noqa: BLE001
            if _reply_target_gone(error):
                raise    # not the clip's fault; the caller re-threads
            # Usually the file is over Telegram's 20 MB by-URL limit. The
            # thumbnail is still a picture of the same thing.
            log.warning("Could not send the %s for post %s (%s) — trying the "
                        "thumbnail", video_kind or "clip", post_id, error)
            db.bump_counter("video_dropped_failed")

    if message_id is None and image_url:
        try:
            message_id = await telegram_client.send_photo(
                image_url, message,
                reply_to_message_id=reply_to_message_id,
            )
        except Exception as error:  # noqa: BLE001
            if _reply_target_gone(error):
                raise    # not the picture's fault; the caller re-threads
            # Telegram fetches images itself and sometimes cannot.
            # Never lose a post over a picture.
            log.warning("Could not send the image for post %s (%s) — "
                        "sending as text instead", post_id, error)
            db.bump_counter("image_dropped_failed")

    if message_id is None:
        message_id = await telegram_client.send_text(
            message,
            reply_to_message_id=reply_to_message_id,
        )
    return message_id


async def execute(item, post_html: str, post_id: int,
                  reply_to_message_id: int | None = None) -> bool:
    """Send one approved post. True if it arrived.

    `reply_to_message_id` threads the post under an earlier one, for
    continuations. Failures are counted on the post row and eventually give up.
    """
    topic = item["topic"] or item["topic_hint"] or "crypto"
    message = compose(post_html, item["url"] or "")
    image_url = item["image_url"] or ""
    video_url = item["video_url"] or ""
    video_kind = item["video_kind"] or ""

    try:
        while True:
            try:
                message_id = await _deliver(post_id, message, image_url, video_url,
                                            video_kind, reply_to_message_id)
                break
            except Exception as error:  # noqa: BLE001
                if reply_to_message_id is None or not _reply_target_gone(error):
                    raise
                # Someone deleted the story's opening post in the channel. Take it
                # out of the story, then thread under whatever post is left.
                log.warning("Message %s was deleted from the channel — removing it "
                            "from its story and sending post %s without it",
                            reply_to_message_id, post_id)
                story_id = db.mark_message_deleted(reply_to_message_id)
                remaining = db.get_story_posts(story_id) if story_id else []
                reply_to_message_id = (remaining[0]["telegram_message_id"]
                                       if remaining else None)

        db.mark_post_sent(post_id, message_id, telegram_client.build_post_url(message_id))
        db.set_item_status(item["id"], "published", f"sent as message {message_id}")
        db.bump_counter("published")

        log.info("Published [%s] %s", topic, (item["title"] or "")[:70])
        return True

    except Exception as error:  # noqa: BLE001
        attempts = db.bump_send_attempts(post_id)
        log.warning("Could not send post %s (attempt %d of %d): %s",
                    post_id, attempts, config.MAX_ATTEMPTS, error)

        if attempts >= config.MAX_ATTEMPTS:
            db.set_post_status(post_id, "send_failed")
            db.set_item_status(item["id"], "failed", f"could not send: {error}")
            db.bump_counter("send_failed")

            from utils import telegram_error
            telegram_error.send_error(
                f"Gave up sending a post after {attempts} attempts: {error}",
                node_name="publisher",
            )
        else:
            # Back into the queue, or it sits at 'written' forever and a single
            # failed send quietly loses a finished post. The post row survives,
            # so the retry does not pay to write it again.
            db.set_item_status(item["id"], "queued", "send failed, will retry")
        return False


async def pause_between_sends() -> None:
    """Wait a moment between messages, so a burst never looks like a burst."""
    await asyncio.sleep(config.SECONDS_BETWEEN_SENDS)
