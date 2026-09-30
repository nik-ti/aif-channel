"""Decides whether two items report the same event, and it is a model rather than a
number because embeddings are unreliable on short text. Measured on 19
hand-labelled pairs, real duplicates scored 0.738 to 0.993 and different stories
0.785 to 0.900, so no cutoff separates them; lowering the threshold to 0.72
caught every duplicate but doubled the false merges.

Two failures it fixed: three separate posts about one Fed decision (0.738, 0.745
and 0.797 against a 0.80 cutoff), and "$49.75M outflows" being merged into
"$32.11M inflows" at 0.900.

It is fed by check 4 rather than replacing it, and runs about 16 times a day. It
fails open, so an unreachable judge means "not a duplicate", and every fallback
is counted as judge_error.
"""

from __future__ import annotations

import asyncio

import config
from utils import db, logger as log_setup, openrouter

log = log_setup.get("judge")


# Binary prompt (kept for tools/check_dedup.py); each "NOT same" line is real
# failure—removing it brings bug back.

SYSTEM = """You decide whether two news items report THE SAME SPECIFIC EVENT.

Same event = the same occurrence, on the same occasion. One is a re-report of
the other, possibly by a different outlet, in different words, at a different
length. A short tweet and a long article about one happening ARE the same event.

NOT the same event, even when the subject and the wording look nearly identical:
  - opposite outcomes (inflows vs outflows, rose vs fell, approved vs rejected)
  - different figures for a recurring measurement (daily flows, weekly totals)
  - a recurring column or roundup published on a different date
  - a reaction, analysis or consequence rather than the occurrence itself
  - the same person or body doing a different thing on a different occasion

Judge the STORY, not the headline. Outlets hook the same event on different
angles — "X worked for a disgraced trader" and "X's fund is raising cash" were
one story, and only the body said so. Read both bodies before deciding.

An update that revises the SAME occurrence — a death toll rising, a figure being
refined as the story develops — IS the same event.

Judge only what the two texts say. Do not use outside knowledge to connect them.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "same_event": {"type": "boolean"},
        "reason": {"type": "string", "description": "One short sentence."},
    },
    "required": ["same_event", "reason"],
    "additionalProperties": False,
}


# Three-way prompt (brain detects continuations): also distinguishes new developments
# from different stories (thread events, not drop all).

SYSTEM_THREE_WAY = """You classify the relationship between two news items.

The OLDER item is one the channel has already published. The NEWER item just
arrived. Decide whether the newer item is:

1. SAME EVENT — it reports the same specific happening as the older item, just
   in different words, from a different outlet, or at a different length.
   Examples: "Fed holds rates steady" and "Fed leaves rates unchanged" about the
   same meeting; a short tweet and a long article about one company being hacked.

2. CONTINUATION — it is a genuine NEW development in the same ongoing story, not
   a re-report. It adds a material fact that changes what a reader knows:
   - a number updated (death toll, losses, inflows/outflows)
   - a new actor or participant has entered the story
   - a proposal moved to a decision (Senate passes the bill that was proposed)
   - a consequence or official reaction that is itself a new event
   - a confirmation of an earlier report from a new authoritative source
   Examples: "The port operator confirms loading has stopped" after "Drones halt
   loading at port"; "Death toll rises to 120" after "Blast kills dozens".

3. DIFFERENT — the two items are about the same broad subject but report
   different happenings, or they are unrelated.

NOT same event, even when the wording looks nearly identical:
  - opposite outcomes (inflows vs outflows, rose vs fell, approved vs rejected)
  - different figures for a recurring measurement (daily ETF flows, weekly totals)
  - a recurring column or roundup published on a different date
  - a reaction, analysis or opinion rather than an occurrence itself
  - the same person or body doing a different thing on a different occasion

An update that revises the SAME occurrence — a death toll rising for the same
blast, a figure being refined — is SAME EVENT, not CONTINUATION. The difference
is whether the newer item adds a NEW development or just re-states/revises the
old one.

Judge only what the two texts say. Do not use outside knowledge.
"""

SCHEMA_THREE_WAY = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["same_event", "continuation", "different"],
        },
        "reason": {"type": "string", "description": "One short sentence."},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}


def _describe(item, when: str) -> str:
    """Render one item for the prompt.

    The timestamp is deliberate: the hardest pairs are recurring reports that
    differ ONLY by date, which the model cannot see unless told.
    """
    title = (item["title"] or "").strip()
    body = (item["body"] or "").strip()[:300]
    source = item["source_name"]
    return f"[{source}, {when}]\n{title}\n{body}".strip()


async def _judge(item, candidate, *, system: str, schema: dict,
                 schema_name: str) -> dict | None:
    """Call the judge model once and return the parsed reply, or None on failure.

    None means "could not get a verdict" — callers fail open.
    """
    user = (
        f"ITEM A (newer):\n{_describe(item, item['fetched_at'])}\n\n"
        f"---\n\n"
        f"ITEM B (older):\n{_describe(candidate, candidate['fetched_at'])}\n\n"
    )

    try:
        answer = await asyncio.wait_for(
            openrouter.chat_json(
                model=config.JUDGE_MODEL,
                system=system,
                user=user,
                schema=schema,
                schema_name=schema_name,
                temperature=0.0,
                # A ceiling, not a charge: a model answering in 40 tokens costs
                # 40 whatever this says. It was 200, which is under what a
                # reasoning model spends thinking before it writes anything, so
                # the reply came back empty and the caller failed open. Four of
                # this week's seven placement failures were exactly that.
                max_tokens=700,
            ),
            timeout=config.JUDGE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        db.bump_counter("judge_error")
        log.warning("Judge timed out after %ss on items %s/%s — treating as new",
                    config.JUDGE_TIMEOUT_SECONDS, item["id"], candidate["id"])
        return None
    except Exception as error:  # noqa: BLE001 - never drop news over an infra blip
        db.bump_counter("judge_error")
        log.warning("Judge failed on items %s/%s (treating as new): %s",
                    item["id"], candidate["id"], error)
        return None

    return answer


async def execute(item, candidate) -> tuple[bool | None, str]:
    """Rule on one pair. Returns (same_event, reason); None means no answer.

    "continuation" counts as NOT a duplicate here — the brain picks those up
    via execute_three_way.
    """
    answer = await _judge(item, candidate, system=SYSTEM, schema=SCHEMA,
                          schema_name="same_event")

    if answer is None:
        return None, "judge unavailable"

    if "same_event" not in answer:
        db.bump_counter("judge_error")
        log.warning("Judge returned no verdict for items %s/%s: %r",
                    item["id"], candidate["id"], answer)
        return None, "no verdict in reply"

    same = bool(answer["same_event"])
    reason = str(answer.get("reason", ""))[:300]
    db.bump_counter("judge_same" if same else "judge_different")
    return same, reason


async def execute_three_way(item, candidate) -> tuple[str | None, str]:
    """Classify a pair for the brain: same_event | continuation | different.

    (None, reason) when the judge cannot be reached — callers must fail open.
    """
    answer = await _judge(item, candidate, system=SYSTEM_THREE_WAY,
                          schema=SCHEMA_THREE_WAY, schema_name="relationship")

    if answer is None:
        return None, "judge unavailable"

    verdict = str(answer.get("verdict", "")).lower()
    reason = str(answer.get("reason", ""))[:300]

    if verdict not in {"same_event", "continuation", "different"}:
        db.bump_counter("judge_error")
        log.warning("Judge returned unexpected verdict %r for items %s/%s",
                    verdict, item["id"], candidate["id"])
        return None, "unexpected verdict"

    db.bump_counter(f"judge_{verdict}")
    return verdict, reason


