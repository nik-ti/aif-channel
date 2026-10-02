"""One function per station in the editorial graph, each a thin wrapper around the
node in nodes/ that does the real work.

A dry run reaches exactly the same decisions but publishes nothing and changes no
statuses, except that dedup still records what it matched. When a model cannot be
reached the item's attempt count goes up, and after MAX_ATTEMPTS it is marked
failed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import config
from brain import persona_loader
from nodes import (article, calendar, dedup, echo, editor, image_analyst, media, publisher,
                   sorter, stories, video_analyst, writer)
from utils import db, logger as log_setup

log = log_setup.get("brain")

# EXECUTION problems fixable by one more draft; CONTENT problems (NO_NEWS, WRONG_TOPIC,
# HYPE, INJECTION, UNSAFE) not fixable, dropped.
FIXABLE_RULES = frozenset({
    "FACTUAL_DRIFT", "OVERCLAIM", "INCOMPLETE", "BROKEN_HTML", "TOO_LONG",
    "EMPTY_BODY",
})

# Two rules: "worth posting" not "post any good". Forced items skip these; others still
# enforced (override ≠ publish broken/untrue).
EDITORIAL_RULES = frozenset({"NO_NEWS", "WRONG_TOPIC"})


# Routing: outcome set means journey over (empty = continue).

def route_after_dedup(state: dict) -> str:
    return "drop" if state.get("outcome") else "sort"


def route_after_sorter(state: dict) -> str:
    return "end" if state.get("outcome") else "place"


async def fetch_article_node(state: dict) -> dict[str, Any]:
    """Read article (writer needs more than headline). Runs on sorter-kept items only.
    Fails open: no article = headline post.
    """
    if state.get("dry_run") or state.get("sweep"):
        return {}
    await article.fetch_for(state["item"])
    return {}


def route_after_story_organizer(state: dict) -> str:
    # Placement still runs when the pacing limits forbid posting. An item that
    # is not filed into its story before QUEUE_TTL_MINUTES expires takes its
    # content out of that story with it, and the story never learns of it.
    return "end" if state.get("place_only") else "gate"


def route_after_gatekeeper(state: dict) -> str:
    return "end" if state.get("outcome") else "write"


def route_after_writer(state: dict) -> str:
    return "end" if state.get("outcome") else "edit"


def route_after_repeat_check(state: dict) -> str:
    return "end" if state.get("outcome") else "send"


def route_after_editor(state: dict) -> str:
    if state.get("outcome"):
        return "end"
    return "rewrite" if state.get("rewrite_requested") else "publish"


async def dedup_node(state: dict) -> dict[str, Any]:
    """Drop already-covered items. "Continues something" answer moved to story layer (sees
    all stories).
    """
    item = state["item"]
    if state.get("sweep"):
        return {}          # judged when it first arrived
    verdict, matched_id, score = await dedup.classify(
        item, with_meaning=True, persist=not state.get("dry_run", False))

    if verdict != "duplicate":
        return {}

    dry = state.get("dry_run", False)

    # The same TEXT, by link, headline, wording or a near-identical vector.
    # Nothing is lost by dropping it, so it is still dropped.
    if score >= config.COSINE_CERTAIN or not matched_id:
        if not dry:
            reason = (f"duplicate of item {matched_id} (same wording as a recent story)"
                      if matched_id else "same event as a recent story")
            db.set_item_status(item["id"], "duplicate", reason)
            db.bump_counter("deduped_fuzzy" if score >= 100 else "deduped_meaning")
        return {"outcome": "duplicate"}

    # The judge ruled "same event" on two items written differently. Different
    # words carry different facts, and dropping the later one destroyed them: on
    # 30 September "U.S. CORE PCE FALLS BELOW EVERY ANALYST FORECAST — below the
    # entire range of 51 Bloomberg forecasts" was thrown away as a repeat of a
    # thinner item about the same print. It is filed with that event instead, as
    # fuel for the story's next post, and gets no post of its own.
    home = None if dry else db.story_of_item(matched_id)

    if home is not None and home["status"] == "live":
        if not dry:
            db.attach_item_to_story(item["id"], int(home["id"]))
            db.set_item_status(
                item["id"], "held",
                f"same event as item {matched_id}; filed in story {home['id']} "
                f"so its details reach that story's next post")
            db.bump_counter("deduped_filed")
        log.info("Item %s repeats item %s — filed in story %s instead of dropped",
                 item["id"], matched_id, home["id"])
        return {"outcome": "held"}

    # The item it supposedly repeats never reached a live story, so the reader was
    # never told any of it and there is nothing to be a repeat of. This is the
    # mistake that suppressed three accounts of one inflation print against an
    # item whose post turned out to be about something else entirely.
    log.info("Item %s matches item %s, but that one is in no live story — "
             "letting it through", item["id"], matched_id)
    if not dry:
        db.bump_counter("deduped_let_through")
    return {}


async def sorter_node(state: dict) -> dict[str, Any]:
    """Score the item and apply the importance gate."""
    item = state["item"]
    item_id = item["id"]
    dry = state.get("dry_run", False)

    if state.get("sweep") or state.get("forced"):
        # A roundup was judged when it first arrived. A forced item was judged
        # too, and a human disagreed — asking the same model again would only
        # produce the same answer that is being overruled.
        why = "roundup" if state.get("sweep") else "forced past the sorter"
        return {"sorter_verdict": {"topic": item.get("topic") or "", "importance": item.get("importance") or 0,
                                   "market": item.get("market") or "", "relevant": True,
                                   "reason": why, "fallback": False}}

    verdict = await sorter.execute(item)

    # Unreachable scorer: we do not know if it matters, so requeue rather than
    # publish or drop.
    if verdict["fallback"]:
        if dry:
            return {"sorter_verdict": verdict, "outcome": "sorter_error"}
        attempts = db.bump_attempts(item_id)
        if attempts >= config.MAX_ATTEMPTS:
            db.set_item_status(item_id, "failed", "could not be scored")
            return {"sorter_verdict": verdict, "outcome": "failed"}
        return {"sorter_verdict": verdict, "outcome": "retry"}

    if not dry:
        db.set_item_sorting(item_id, verdict["topic"], verdict["importance"],
                            verdict["market"], verdict.get("reason", ""))

    if not verdict["relevant"]:
        if not dry:
            db.set_item_status(item_id, "irrelevant", verdict["reason"])
            db.bump_counter("irrelevant")
        return {"sorter_verdict": verdict, "outcome": "irrelevant"}

    # The importance gate — the main control on how trivial the channel feels.
    min_importance = config.MIN_IMPORTANCE

    if verdict["importance"] < min_importance:
        if not dry:
            db.set_item_status(
                item_id, "low_impact",
                f"impact {verdict['importance']}/5 (market: {verdict['market']}), below "
                f"the {min_importance} threshold: {verdict['reason']}",
            )
            db.bump_counter("below_importance")
        return {"sorter_verdict": verdict, "outcome": "low_impact"}

    # Carry the verdict on the item so the writer and editor see the topic the
    # sorter decided.
    updated_item = dict(item)
    updated_item["topic"] = verdict["topic"]
    updated_item["importance"] = verdict["importance"]
    updated_item["market"] = verdict["market"]

    return {"sorter_verdict": verdict, "item": updated_item}


# =============================================================================
# STATION 3: which story is this, and has it moved?
# =============================================================================

async def story_organizer_node(state: dict) -> dict[str, Any]:
    """Put the item into a running story, or open one for it.

    The only station that sees the incoming item and the channel's own output
    together. Fails open into a NEW story: a wrongly separated item is one extra
    post, which is what the channel did for every item before this existed.
    """
    item = state["item"]
    now = datetime.now(timezone.utc)
    dry = state.get("dry_run", False)

    # Resume first, before paying for a model call. A writer or editor retry
    # leaves the item queued with its story_id already set, and re-placing it
    # would either burn a call or file it somewhere else than the first time.
    existing_id = item.get("story_id")
    if existing_id:
        row = db.get_story(existing_id)
        if row is not None and row["status"] == "live":
            story = stories.load_one(existing_id, now)
            if story is not None:
                log.info("Item %s resumes story %s", item["id"], existing_id)
                return {"story": story, "story_id": story.id}

    # A scheduled release is not a guess. The calendar named it before it
    # happened, so every item about it belongs to one story, found by that name
    # and not by asking a model which of thirty open stories looks closest. This
    # is the branch that stops a PCE print landing in a story about Fed speeches.
    release = item["calendar_key"] if "calendar_key" in item.keys() else ""
    if release and not dry:
        existing = db.story_for_calendar_key(release)
        if existing is not None:
            db.attach_item_to_story(item["id"], int(existing["id"]))
            story = stories.load_one(int(existing["id"]), now)
            if story is not None:
                log.info("Item %s joins story %s: same scheduled release (%s)",
                         item["id"], story.id, item["calendar_title"])
                return {"story": story, "story_id": story.id}
        headline = (item["title"] or "")[:200]
        story_id = db.create_story(headline=headline, summary=headline,
                                   item_id=item["id"], at=db.now_iso(),
                                   calendar_key=release)
        db.set_story_name(story_id, (item["calendar_title"] or headline)[:80])
        story = stories.load_one(story_id, now)
        log.info("Item %s opens story %s for the scheduled release %s",
                 item["id"], story_id, item["calendar_title"])
        return {"story": story, "story_id": story_id}

    open_stories = stories.load_open(now)
    home, why, could_ask = await stories.place(item, open_stories, now)

    if not could_ask:
        # The model could not be reached or its answer could not be read. That
        # is not an answer, and guessing "new story" here publishes duplicates:
        # a story with no posts always sends its first. Leave it queued; the
        # next round is two minutes away and it has 90 to spend.
        if not dry:
            db.set_item_status(item["id"], "queued", "waiting to be placed again")
        return {"outcome": "retry"}

    if home is None:
        headline = (item["title"] or "")[:200]
        if dry:
            story = stories.Story(id=0, headline=headline, summary=headline)
            story.absorb(dict(item), now)
        else:
            story_id = db.create_story(headline=headline, summary=headline,
                                       item_id=item["id"], at=db.now_iso())
            # A short name for the thread, so a list of stories reads as a list
            # of situations rather than of whichever wire item opened each one.
            # Nothing depends on it: a story with no name still works.
            await stories.name_story(story_id, f"{headline}\n\n{(item['body'] or '')[:400]}")
            story = stories.load_one(story_id, now)
            db.bump_counter("story_opened")
        log.info("Item %s opens story %s: %s", item["id"], story.id, why[:120])
    else:
        if dry:
            home.absorb(dict(item), now)
            story = home
        else:
            db.attach_item_to_story(item["id"], home.id)
            # Re-read rather than patch in memory, so the gate and the writer
            # see exactly the rows the database holds — including the topic and
            # importance the sorter wrote onto older pending items.
            story = stories.load_one(home.id, now)
            db.bump_counter("story_joined")
        log.info("Item %s joins story %s: %s", item["id"], story.id, why[:120])

    if state.get("place_only"):
        # Left queued on purpose: next round resumes this story for free.
        return {"story": story, "story_id": story.id, "outcome": "placed"}

    return {"story": story, "story_id": story.id}


async def gatekeeper_node(state: dict) -> dict[str, Any]:
    """Decide whether the story has moved enough to be worth a post.

    Three answers. "post" folds the whole story into the writer's source;
    "hold" leaves the item as fuel for the story's next post; "not this story"
    undoes a bad placement instead of silencing what it misfiled — that last one
    is why a mis-placed "Fed rate hike odds 66%" is not lost any more.
    """
    item = state["item"]
    story = state["story"]
    now = datetime.now(timezone.utc)
    dry = state.get("dry_run", False)

    if state.get("forced"):
        # This item goes to the writer ALONE, not folded together with whatever
        # else the story had waiting. You forced this one, so this one is what
        # gets written — otherwise the story's other pending items crowd it out
        # and the post is about something you did not ask for.
        #
        # It stays filed in the story, which is the other half of the point: the
        # next item on the same story has to know this was covered.
        log.info("Item %s forced to the writer on its own, filed in story %s",
                 item["id"], story.id)
        return {"story_angle": "",
                "story_brief": stories.brief_for_writer(story, "", single_item=True),
                "gate_reason": "forced", "trigger_item_id": item["id"]}

    verdict = await stories.should_post(story, now, roundup=bool(state.get("sweep")))

    if verdict["verdict"] == "not_this_story":
        log.info("Item %s does not belong in story %s (%s) — giving it its own",
                 item["id"], story.id, verdict["reason"][:100])
        headline = (item["title"] or "")[:200]
        if dry:
            story.eject(dict(item))
            story = stories.Story(id=0, headline=headline, summary=headline)
            story.absorb(dict(item), now)
        else:
            db.detach_item_from_story(item["id"])
            story_id = db.create_story(headline=headline, summary=headline,
                                       item_id=item["id"], at=db.now_iso())
            story = stories.load_one(story_id, now)
            db.bump_counter("story_ejected")
        # A story with no posts always speaks, so this cannot end in silence.
        verdict = await stories.should_post(story, now)

    if verdict["verdict"] != "post":
        if not dry:
            db.set_item_status(item["id"], "held",
                               f"story {story.id}: {verdict['reason']}")
            db.bump_counter("story_held")
        log.info("Holding item %s on story %s: %s",
                 item["id"], story.id, verdict["reason"][:120])
        return {"outcome": "held", "story": story, "story_id": story.id,
                "gate_reason": verdict["reason"]}

    log.info("Posting on story %s from item %s: %s",
             story.id, item["id"], verdict["reason"][:120])

    # Folding the story into state["item"] is the one seam: every station after
    # this keeps working on "an item" and needs to know nothing about stories.
    return {
        "item": stories.as_source(story),
        "trigger_item_id": item["id"],
        "story": story,
        "story_id": story.id,
        "story_angle": verdict["angle"],
        "story_brief": stories.brief_for_writer(story, verdict["angle"]),
    }


async def writer_node(state: dict) -> dict[str, Any]:
    """Produce the post text from the story the gate approved.

    state["item"] is no longer one wire item: the gate replaced it with the
    story's pending items folded into one source. The writer's rules are
    unchanged and still bind — every fact must appear in the text it is given —
    but that text is now the whole story rather than one wire.

    On a rewrite pass state["editor_feedback"] carries the rejection reason and
    state["post_id"] points at the existing draft, whose text is REPLACED rather
    than a second post row being created.
    """
    item = state["item"]
    item_id = item["id"]
    dry = state.get("dry_run", False)
    has_image = bool(item.get("image_url") or item.get("video_url"))
    feedback = state.get("editor_feedback") or ""
    existing_post_id = state.get("post_id")

    # Voice context for the writer: the persona file plus recent published posts.
    # These are loaded inside the node rather than in the graph state because
    # they do not need to survive across items and are not part of routing.
    persona = persona_loader.load_persona()
    recent_posts = persona_loader.get_recent_posts()

    used_ai = True
    writer_kwargs = {
        "has_image": has_image,
        "editor_feedback": feedback,
        "persona": persona,
        "recent_posts": recent_posts,
        "brief": state.get("story_brief", ""),
    }

    post_html = await writer.execute(item, **writer_kwargs)

    if not post_html:
        # Writing can fail for reasons that pass on their own. Leave it queued.
        if dry:
            return {"outcome": "write_failed", "editor_feedback": "",
                    "rewrite_requested": False}
        attempts = db.bump_attempts(item_id)
        if attempts >= config.MAX_ATTEMPTS:
            db.set_item_status(item_id, "failed",
                               f"the writer failed {attempts} times")
            db.bump_counter("write_failed")
            return {"outcome": "failed"}
        return {"outcome": "retry"}

    if dry:
        # No post row in a rehearsal — the editor runs with record=False.
        return {"post_html": post_html, "used_ai": used_ai, "post_id": 0,
                "editor_feedback": "", "rewrite_requested": False}

    if existing_post_id:
        # Rewrite pass: the draft row already exists.
        db.update_post_text(existing_post_id, post_html)
        post_id = existing_post_id
    else:
        post_id = db.create_post(
            item_id=item_id,
            topic=item.get("topic") or state["sorter_verdict"]["topic"],
            post_html=post_html, image_url=item.get("image_url") or "",
            writer_model=writer.MODEL,
            source_context={"source_items": item.get("source_items") or [
                {"id": item_id, "source_name": item["source_name"], "url": item["url"]}],
                "title": item["title"], "body": (item["body"] or "")[:config.MAX_BODY_CHARS],
                "calendar": calendar.describe(item)},
        )
        if post_id is None:
            # A previous run got this far before stopping. Reuse its post.
            existing = db.get_post_by_item(item_id)
            if existing is None:
                db.set_item_status(item_id, "failed", "post row went missing")
                return {"outcome": "failed"}
            post_id, post_html = existing["id"], existing["post_html"]

        db.set_item_status(item_id, "written", "waiting on the editor")
        db.bump_counter("written")

    return {"post_html": post_html, "used_ai": used_ai, "post_id": post_id,
            "editor_feedback": "", "rewrite_requested": False}


# =============================================================================
# STATION 5: the editor decides
# =============================================================================

async def editor_node(state: dict) -> dict[str, Any]:
    """Judge the finished post against its source. Fails closed.

    A rejection naming ONLY fixable rules goes back to the writer once with the
    reason. The post is not marked declined until a rejection is final, so a
    rejected-then-fixed draft never shows up in the decline statistics.
    """
    item = state["item"]
    dry = state.get("dry_run", False)
    rewrite_count = state.get("rewrite_count", 0)

    # A story's fourth post pointing back at what the channel already said is
    # not the writer inventing facts — but without the earlier post in front of
    # it, that is exactly what the editor sees.
    story = state.get("story")
    parent_post = story.posts[-1] if story and story.posts else ""

    decision = await editor.execute(
        item, state["post_html"], state["post_id"],
        record=not dry,
        attempt=rewrite_count + 1,
        parent_post=parent_post,
    )

    if decision["error"]:
        # No verdict means nothing is published.
        if dry:
            return {"editor_verdict": decision, "outcome": "editor_error",
                    "rewrite_requested": False}
        attempts = db.bump_attempts(item["id"])
        if attempts >= config.MAX_ATTEMPTS:
            db.set_item_status(item["id"], "failed", "could not reach the editor")
            return {"editor_verdict": decision, "outcome": "failed",
                    "rewrite_requested": False}
        db.set_item_status(item["id"], "queued", "waiting to be re-judged")
        return {"editor_verdict": decision, "outcome": "retry",
                "rewrite_requested": False}

    if not decision["approved"]:
        rules = set(decision["rules_broken"])

        if state.get("forced") and rules and rules <= EDITORIAL_RULES:
            log.info("Item %s: editor said %s, overruled because it was forced",
                     item["id"], ", ".join(sorted(rules)))
            decision = {**decision, "approved": True,
                        "reason": f"forced past {', '.join(sorted(rules))}"}
            return {"editor_verdict": decision, "rewrite_requested": False}

        # Fixable and not yet rewritten: back to the writer with the reason.
        if rules and rules <= FIXABLE_RULES and rewrite_count < config.MAX_REWRITES:
            feedback = f"{', '.join(decision['rules_broken'])}: {decision['reason']}"
            log.info("Editor asked for a rewrite of item %s: %s", item["id"], feedback[:150])
            if not dry:
                db.set_item_status(item["id"], "written",
                                   f"editor asked for a rewrite: {feedback[:200]}")
            return {"editor_verdict": decision, "editor_feedback": feedback,
                    "rewrite_count": rewrite_count + 1, "rewrite_requested": True}

        # Final rejection.
        if not dry:
            db.set_post_status(state["post_id"], "declined")
            # Not "irrelevant": that is the sorter's word for "not our subject",
            # decided before anything is written. This item WAS our subject and
            # cleared the bar — what failed is the post. One word for both made
            # the dashboard say a story had been judged uninteresting when it
            # had actually been written and thrown away.
            db.set_item_status(
                item["id"], "declined",
                f"editor rejected it {decision['rules_broken']}: {decision['reason']}",
            )
        return {"editor_verdict": decision, "outcome": "declined",
                "rewrite_requested": False}

    if not dry:
        db.set_post_status(state["post_id"], "approved")

    return {"editor_verdict": decision, "rewrite_requested": False}


# =============================================================================
# STATION 6: send it
# =============================================================================

async def repeat_check_node(state: dict) -> dict[str, Any]:
    """Refuse to send a post that tells the reader what a recent post already did.

    The exit, so nothing routes around it. Everything upstream asks a narrower
    question: dedup compares wire items, the gatekeeper compares one story's
    posts and only where it reasons. This compares the finished post against
    everything the channel published recently.

    A held item keeps its story, so its content still reaches the reader through
    that story's next post.
    """
    if state.get("dry_run"):
        return {}

    repeats, why = await echo.repeats_something_published(state["post_html"])
    if not repeats:
        return {}

    item = state["item"]
    db.set_post_status(state["post_id"], "declined")
    db.set_item_status(item["id"], "held", why)
    return {"outcome": "held"}


def _media_source(item):
    """The item as the analysts should see it: a folded story as is, a lone item re-read.

    A lone item (a forced post) is the row read before fetch_article stored its
    page's media, so it is read again to pick those up.
    """
    if media._get(item, "candidate_media", None):
        return item
    return db.get_item(item["id"]) or item


async def image_analyst_node(state: dict) -> dict[str, Any]:
    """Choose the picture for the post, or none. Records the choice on the post row.

    On a channel that does not check clips, a clip goes out unchecked as before,
    and the picture chosen here is only its fallback.
    """
    post_id = state.get("post_id")
    if state.get("dry_run") or not post_id:
        return {}
    found = media.candidates(_media_source(state["item"]))
    text = persona_loader.visible_text(state.get("post_html", ""))
    try:
        choice = await image_analyst.choose(text, found.images)
    except Exception as error:  # noqa: BLE001 - the post goes out without a picture
        log.exception("Image analyst crashed on post %s: %s", post_id, error)
        choice = image_analyst.Choice(reason=f"check crashed: {error}"[:200], failed=True)

    fields = {"media_image_url": choice.url, "media_note": f"image: {choice.reason}"}
    if found.videos and not config.CHECK_VIDEOS:
        fields["media_video_url"] = found.videos[0]["url"]
        fields["media_video_kind"] = found.videos[0].get("kind") or "video"
        fields["media_note"] += " | video: sent unchecked, this channel does not check clips"
    db.set_post_media(post_id, **fields)
    return {}


async def video_analyst_node(state: dict) -> dict[str, Any]:
    """Choose the clip for the post, or none. A chosen clip goes out ahead of the picture."""
    post_id = state.get("post_id")
    if state.get("dry_run") or not post_id:
        return {}
    found = media.candidates(_media_source(state["item"]))
    if not found.videos:
        return {}
    text = persona_loader.visible_text(state.get("post_html", ""))
    try:
        choice = await video_analyst.choose(text, found.videos)
    except Exception as error:  # noqa: BLE001 - the post goes out without a clip
        log.exception("Video analyst crashed on post %s: %s", post_id, error)
        choice = image_analyst.Choice(reason=f"check crashed: {error}"[:200], failed=True)

    before = db.get_post_media(post_id)
    note = ((before["media_note"] + " | ") if before and before["media_note"] else "")
    db.set_post_media(post_id, media_video_url=choice.url, media_video_kind=choice.kind,
                      media_note=f"{note}video: {choice.reason}")
    return {}


async def publish_node(state: dict) -> dict[str, Any]:
    """Send the approved post, then book it against its story. Dry-run stops here."""
    if state.get("dry_run"):
        return {"outcome": "approved"}

    item = state["item"]
    story = state.get("story")
    reply_to = story.first_message_id if story and story.posts else None
    sent = await publisher.execute(item, state["post_html"], state["post_id"],
                                   reply_to_message_id=reply_to)

    if sent and state.get("story_id"):
        # Only after the send. Booking marks every other item of the story as
        # covered, and doing that for a message that never arrived would bury
        # their content with nothing published in its place.
        db.record_story_post(
            state["story_id"], item["id"],
            persona_loader.visible_text(state["post_html"]),
            # A forced post was written from one item alone, so it covered
            # nothing else the story was holding.
            covers_others=not state.get("forced", False),
        )

    return {"outcome": "published" if sent else "retry"}


# The stations this codebase provides, and how each one routes onward.
# "next" means the following stage in the channel's PIPELINE, "end" stops the
# item. A channel that needs a station of its own adds it to this mapping from
# its channels/<name>/nodes.py, then names it in its PIPELINE.
STAGES: dict[str, tuple] = {
    "dedup":           (dedup_node,            route_after_dedup,
                        {"drop": "end", "sort": "next"}),
    "sorter":          (sorter_node,           route_after_sorter,
                        {"place": "next", "end": "end"}),
    "fetch_article":   (fetch_article_node,    None, {}),
    "story_organizer": (story_organizer_node,  route_after_story_organizer,
                        {"gate": "next", "end": "end"}),
    "gatekeeper":      (gatekeeper_node,       route_after_gatekeeper,
                        {"write": "next", "end": "end"}),
    "writer":          (writer_node,           route_after_writer,
                        {"edit": "next", "end": "end"}),
    "editor":          (editor_node,           route_after_editor,
                        {"publish": "next", "rewrite": "writer", "end": "end"}),
    "repeat_check":    (repeat_check_node,     route_after_repeat_check,
                        {"send": "next", "end": "end"}),
    "image_analyst":   (image_analyst_node,    None, {}),
    "video_analyst":   (video_analyst_node,    None, {}),
    "publish":         (publish_node,          None, {}),
}
