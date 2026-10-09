"""The two story stations and the story-aware dedup station, copied from pipeline/stations.py
on 2026-10-09 when AI Flow switched stories off. Reference for restoring; not imported anywhere."""

async def dedup_node(state: dict) -> dict[str, Any]:
    """Drop already-covered items. "Continues something" answer moved to story layer (sees
    all stories).
    """
    item = state["item"]
    if state.get("sweep") or state.get("released") or state.get("digest"):
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

    if not config.STORIES:
        return _drop_repeat_without_stories(item, matched_id, dry)

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



async def story_organizer_node(state: dict) -> dict[str, Any]:
    """Put the item into a running story, or open one for it.

    Related closed stories retain their published context and can be reopened.
    Unavailable retrieval or placement leaves the item queued to be asked again.
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

    try:
        open_stories = await stories.placement_candidates(item, now, persist=not dry)
    except semantic_memory.Unavailable as error:
        log.warning("Item %s waits for story memory: %s", item["id"], error)
        if not dry:
            db.set_item_status(item["id"], "queued", f"waiting for story memory: {error}"[:300])
        return {"outcome": "retry"}
    home, why, could_ask = await stories.place(item, open_stories, now, persist=not dry)

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

    verdict = await stories.should_post(story, now, roundup=bool(state.get("sweep")), persist=not dry)

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
        verdict = await stories.should_post(story, now, persist=not dry)

    if verdict["verdict"] == "retry":
        if not dry:
            db.set_item_status(item["id"], "queued", f"waiting for story gate memory: {verdict['reason']}"[:300])
        return {"outcome": "retry", "story": story, "story_id": story.id}

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

