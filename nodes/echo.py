"""The last check before a post is sent: has the reader already been told this?

It stands at the very end, so nothing can route around it, and it compares the
FINISHED POST against the channel's recent posts — the only comparison that
matches what a reader actually sees. It deliberately does not ask dedup's
question. A 30-year Treasury yield closing at 5.59% and touching 5.587% intraday
are different events but the same news to a reader, so this station asks whether
the reader learns anything new instead.

Measured on 60 posts, real repeats scored 0.741 to 0.924 and legitimate posts
0.734 to 0.776, so the number only builds a shortlist and a model rules. It fails
open: no answer means the post goes out.
"""

from __future__ import annotations

import asyncio

import config
from brain import persona_loader
from utils import db, embeddings, logger as log_setup, openrouter, textclean

log = log_setup.get("echo")


SYSTEM = """You are the editor of a news channel, making the last check before a
post is sent.

You are shown a post the channel ALREADY PUBLISHED and a new post about to go
out. The reader saw the published one. Your only question:

  Does the new post tell that reader anything they do not already know?

"hold" means it does not — the reader would finish it thinking "yes, I read
this". "send" means they would finish it knowing something new.

HOLD, even when the figures are not identical:
  - the same measurement at a new reading, still doing the same thing
    ("30-year yield at a 22-year high", then "30-year yield at a 24-year high")
  - a "highest/lowest since <year>" record reaching further back than the one
    already published. A date is not a threshold: "highest since 2002" after
    "highest since 2004" is one measurement still climbing, and so is the same
    figure carried to another decimal place
  - an intraday level and the closing level of one day's move
  - a yield "crossing" 5.3%, 5.5% or any other fraction: that is a new
    reading, not a threshold. Only whole percents — 5%, 6%, 7% — are
    thresholds for a yield
  - a level the published post already described, in different words
  - a consequence the published post already stated or plainly implied
  - another outlet confirming what the published post already reported
  - the same move on a related instrument: the 10-year or 5-year yield doing
    what the published post said the 30-year did. One curve is not a new actor

SEND:
  - the direction reversed (rose then fell, inflows then outflows)
  - a decision where the published post had a proposal, or a confirmation where
    it had an unsourced report
  - a new actor, a new place, or a figure of a DIFFERENT kind
  - a scheduled release covering a NEW period (a monthly CPI print, a weekly
    claims number) — the period is itself the new information
  - a magnitude the reader could not have guessed from the published post: a 2%
    move after a 0.1% move, a death toll of 200 after "dozens killed"
  - a ROUND NUMBER threshold crossed for the first time — a yield passing 5%, a
    market cap passing $5 trillion, an index passing 50,000. The first crossing
    only, never a new reading beyond it, and never a year: "since 2002" is not
    a threshold. For a yield only whole percents count (5%, 6%); 5.3% is
    NOT a round number, nor is $93 for oil

YIELDS AND RATES. A climb the published post already reported is news again
at the next whole percent, not before: 5.23% then 5.30%, or 5.9%, is hold.
Only something besides the level changes that — a sharp jump within one day,
a central bank reacting, a failed auction.

The published post may be several days old. Age is not a reason to send: a
reader told something last week still knows it.

Judge only the two texts in front of you.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["hold", "send"]},
        "reason": {"type": "string", "description": "One short sentence."},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}


async def _already_told(new_text: str, published_text: str, when: str) -> tuple[str | None, str]:
    """Ask whether the new post adds anything. (None, why) when there is no answer."""
    user = (
        f"ALREADY PUBLISHED ({when}):\n{published_text}\n\n"
        f"---\n\n"
        f"ABOUT TO GO OUT:\n{new_text}\n"
    )

    try:
        answer = await asyncio.wait_for(
            openrouter.chat_json(
                model=config.ECHO_MODEL, system=SYSTEM, user=user,
                schema=SCHEMA, schema_name="already_told",
                temperature=0.0, max_tokens=900,
            ),
            timeout=config.JUDGE_TIMEOUT_SECONDS,
        )
    except Exception as error:  # noqa: BLE001 - never stop the channel over a blip
        db.bump_counter("echo_error")
        return None, str(error) or type(error).__name__

    verdict = str(answer.get("verdict", "")).lower()
    if verdict not in {"hold", "send"}:
        db.bump_counter("echo_error")
        return None, f"unexpected verdict {verdict!r}"
    return verdict, str(answer.get("reason", ""))[:300]


async def repeats_something_published(post_html: str) -> tuple[bool, str]:
    """(True, why) when this post tells the reader what a recent post already did."""
    text = persona_loader.visible_text(post_html).strip()
    if not text:
        return False, ""

    recent = db.recent_published_posts(config.ECHO_WINDOW_HOURS, config.ECHO_MAX_COMPARED)
    if not recent:
        return False, ""

    try:
        vector = await embeddings.embed_one(textclean.for_embedding(text))
        if vector is None:
            return False, ""

        best_score, best_text, best_when = 0.0, "", ""
        for row in recent:
            other_text = persona_loader.visible_text(row["post_html"]).strip()
            other = await embeddings.embed_one(textclean.for_embedding(other_text))
            if other is None:
                continue
            score = embeddings.cosine(vector, other)
            if score > best_score:
                best_score, best_text, best_when = score, other_text, row["sent_at"]
    except Exception as error:  # noqa: BLE001
        log.warning("Could not compare against recent posts (%s) — sending", error)
        return False, ""

    if best_score < config.ECHO_SHORTLIST:
        return False, ""

    verdict, reason = await _already_told(text, best_text, best_when)

    if verdict is None:
        log.warning("No verdict on a %.3f match (%s) — sending anyway", best_score, reason)
        return False, ""

    if verdict == "hold":
        log.info("Held: the reader already knows this from a post of %s (%.3f) — %s",
                 best_when, best_score, reason[:120])
        db.bump_counter("echo_held")
        return True, f"the reader already knows this from the post of {best_when}: {reason[:200]}"

    db.bump_counter("echo_sent")
    log.info("Looked alike (%.3f) but adds something — sending: %s", best_score, reason[:120])
    return False, ""
