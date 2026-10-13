"""The sifter: before a follow-up is written, keep only the facts the reader does not have yet.

Runs only when follow_up.related_posts found earlier posts about the same product. A model lists
the source's new facts, each with a quote; code keeps a fact only if its quote is really in the
source. The writer then writes from those facts alone, so it cannot repeat what the reader knows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import config
from nodes import article
from nodes.sorter import _normalize_quote
from utils import logger as log_setup, openrouter

log = log_setup.get("sifter")

MODEL = config.SIFTER_MODEL
PROMPT = config.SIFTER_PROMPT_PATH.read_text()
MAX_TOKENS = 2500          # gemini-2.5-flash thinks first; 800 ran out on a long launch page
_LABEL_LINES = re.compile(r"(?m)^(POST by|QUOTED POST by|@\S+ REPOSTED|LINKED PAGE \d+:|Source:).*$")

SCHEMA = {
    "type": "object",
    "properties": {
        "new_facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"fact": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["fact", "quote"],
                "additionalProperties": False,
            },
        },
        "reason": {"type": "string"},
        "worth_a_post": {"type": "boolean"},
    },
    "required": ["new_facts", "reason", "worth_a_post"],
    "additionalProperties": False,
}


@dataclass
class Sifted:
    facts: list[dict] = field(default_factory=list)
    reason: str = ""
    nothing_new: bool = False     # nothing new, or only trivia not worth a post of its own
    failed: bool = False          # no usable answer: the caller falls back, never drops


def _source(item) -> str:
    """The exact text the sifter reads, which is also what its quotes are checked against."""
    return f"{item['title'] or ''}\n{article.full_source(item)[: config.MAX_BODY_CHARS]}"


async def execute(item, earlier_posts: list[str]) -> Sifted:
    shown = "\n\n".join(f"Earlier post {n}:\n{text}" for n, text in enumerate(earlier_posts, 1))
    user = f"EARLIER POSTS (the reader saw these)\n\n{shown}\n\n---\nNEW SOURCE\n\n{_source(item)}"
    try:
        answer = await openrouter.chat_json(
            model=MODEL, system=PROMPT, user=user, schema=SCHEMA, schema_name="new_facts",
            temperature=0.0, max_tokens=MAX_TOKENS)
        raw = answer.get("new_facts")
        if not isinstance(raw, list):
            raise ValueError("no new_facts list in the answer")
    except Exception as error:  # noqa: BLE001 - an outage must never drop an item
        log.warning("Sifter failed for item %s: %s", item["id"], error)
        return Sifted(reason=f"sifter unavailable: {error}"[:200], failed=True)

    reason = str(answer.get("reason") or "")[:300]
    if not raw:
        return Sifted(reason=reason, nothing_new=True)

    source = _normalize_quote(_LABEL_LINES.sub("", _source(item)))
    facts, dropped = [], []
    for entry in raw:
        quote = _normalize_quote(str((entry or {}).get("quote") or ""))
        fact = str((entry or {}).get("fact") or "").strip()
        if fact and quote and quote in source:
            facts.append({"fact": fact, "quote": quote})
        else:
            dropped.append(fact or quote)
    if facts and answer.get("worth_a_post") is False:
        return Sifted(facts=facts, reason=f"not worth a new post: {reason}"[:300], nothing_new=True)
    if dropped:
        log.info("Sifter: item %s, %d fact(s) dropped, quote not in the source: %s",
                 item["id"], len(dropped), " | ".join(dropped)[:200])
    if not facts:
        # It claimed something new but could not show it: not proof that nothing is new.
        return Sifted(reason=f"every quote was missing from the source; {reason}"[:300], failed=True)
    return Sifted(facts=facts, reason=reason)
