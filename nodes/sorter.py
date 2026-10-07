"""The only station that asks whether an item is worth covering at all. The editor
later checks a post against its source, which is a different question.

The rubric (prompts/rubric.md) makes the model say who can use the thing today
before it scores it, and "nobody" caps the score below the publishing bar.
On a model failure the item goes back to the queue rather than being guessed.
"""

from __future__ import annotations

from datetime import datetime, timezone

import config
from utils import logger as log_setup, openrouter

log = log_setup.get("sorting")

MODEL = config.SORTER_MODEL
TEMPERATURE = 0.0          # consistent judgements, not creative ones

# 250 was too small and answers came back cut off mid-value. A reasoning model
# thinks privately before answering and that counts against this budget too.
MAX_TOKENS = 800

PROMPT = config.RUBRIC_PATH.read_text()

# What an item scores at most when nobody can use it. One below the publishing
# bar on purpose, and enforced here in code: a model that says "none" and then
# scores 4 has contradicted itself, and the concrete answer wins.
NO_USE_CAP = 3

# The shape of the answer. "strict" mode means the provider enforces this, so
# the model cannot invent a topic name or return importance as words.
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["relevant", "topic", config.SORTER_AXIS, "importance", "reason"],
    "properties": {
        "relevant": {"type": "boolean"},
        "topic": {"type": "string", "enum": list(config.TOPICS)},
        config.SORTER_AXIS: {"type": "string", "enum": list(config.SORTER_AXIS_VALUES)},
        "importance": {"type": "integer", "minimum": 1, "maximum": 5},
        "reason": {"type": "string"},
    },
}


def user_message(item) -> str:
    """What the sorter reads about one item."""
    title = item["title"] or ""
    body = (item["body"] or "")[:600]
    article = (item["article_text"] if "article_text" in item.keys() else "") or ""
    if config.SORTER_READS_ARTICLE and article:
        # The feed's snippet (often just "Source: x | Release date: y") plus the article.
        body = f"{body}\n\n{article[:1500]}".strip()
    hint = item["topic_hint"] or "unknown"
    origin = "a post on X" if item["origin"] == "x" else "a news article"
    today = (f"Today is {datetime.now(timezone.utc):%d %B %Y}.\n"
             if config.SORTER_SHOWS_DATE else "")
    return (
        f"{today}Source: {item['source_name']} ({origin})\n"
        f"The source files this under: {hint}\n"
        f"\nHeadline: {title}\n\n"
        f"Text: {body}"
    )


async def execute(item) -> dict:
    """Judge one item. Always returns a usable answer, even when the model fails.

    Returns relevant, topic, market (who can use it; stored in items.market),
    importance (1-5), reason, and fallback (True if the model failed).
    """
    title = item["title"] or ""
    hint = item["topic_hint"] or "unknown"

    try:
        result = await openrouter.chat_json(
            model=MODEL, system=PROMPT, user=user_message(item),
            schema=SCHEMA, schema_name="sorting",
            temperature=TEMPERATURE, max_tokens=MAX_TOKENS,
        )

        topic = result.get("topic", "other")
        relevant = bool(result.get("relevant", False))
        market = str(result.get(config.SORTER_AXIS, "none"))
        if market not in config.SORTER_AXIS_VALUES:
            market = "none"
        importance = int(result.get("importance", 2))
        reason = str(result.get("reason", ""))[:300]

        # "other" is the topic that means "not ours", so it doubles as the filter.
        if topic == "other":
            relevant = False

        if market == "none" and importance > NO_USE_CAP:
            log.info("Capping item %s from %d to %d — the model named nobody who "
                     "can use it (%s)", item["id"], importance, NO_USE_CAP, title[:60])
            importance = NO_USE_CAP
            reason = f"nobody can use it today; {reason}"[:300]

        return {
            "relevant": relevant,
            "topic": topic,
            "market": market,
            "importance": importance,
            "reason": reason,
            "fallback": False,
        }

    except Exception as error:  # noqa: BLE001
        log.warning("Scoring failed for item %s (%s): %s", item["id"], title[:60], error)
        # Neither publish unscored nor drop: fallback=True sends it back to the
        # queue, and it is given up on after MAX_ATTEMPTS tries.
        usable_hint = hint if hint in config.VALID_TOPICS else "other"
        return {
            "relevant": False,
            "topic": usable_hint,
            "market": "none",
            "importance": 0,
            "reason": "could not be scored; will try again",
            "fallback": True,
        }
