"""Find posts the channel already published about the same product or event, before writing.

The writer gets them as a follow-up brief (open with what is new, do not re-introduce, do not
reuse their words) and the editor gets them so a pointer back does not look invented.
shared_phrases is the code check behind "do not reuse their words".
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import config
from nodes import article
from utils import persona_loader, semantic_memory

PHRASE_WORDS = 5
_WORD = re.compile(r"[a-z0-9]+(?:['’.][a-z0-9]+)*")


async def related_posts(item, *, now=None, persist: bool = True) -> list[dict]:
    """Published posts close enough to this item's source to be about the same thing.

    Raises semantic_memory.Unavailable when the memory cannot be searched: the caller waits,
    because writing without this check is how the same launch went out three times.
    """
    text = f"{item['title'] or ''}\n{article.full_source(item)[:1500]}"
    matches = await semantic_memory.published_matches(text, now=now, persist=persist)
    close = [m for m in matches if m["score"] >= config.FOLLOW_UP_SIMILARITY]
    return close[:config.FOLLOW_UP_MAX_POSTS]


def minutes_since_latest(posts: list[dict], *, now=None) -> float | None:
    """How long ago the most recent of these posts went out, or None if none has a time."""
    times = [datetime.fromisoformat(str(row["sent_at"]).replace("Z", "+00:00"))
             for row in posts if row.get("sent_at")]
    if not times:
        return None
    latest = max(t if t.tzinfo else t.replace(tzinfo=timezone.utc) for t in times)
    return ((now or datetime.now(timezone.utc)) - latest).total_seconds() / 60


def writer_section(posts: list[str]) -> str:
    """What the writer is told, right after its source, when its post follows earlier ones."""
    shown = "\n\n".join(f"Earlier post {n}:\n{text}" for n, text in enumerate(posts, start=1))
    return (
        "---\nTHIS POST IS A FOLLOW-UP. WHAT THE READER ALREADY KNOWS:\n\n"
        f"{shown}\n\n---\n"
        "The channel already published the posts above about the same product or event. "
        "Your reader saw them, maybe minutes ago, and may read your post right under them. "
        "\"The source's best facts\" now means the best facts the reader does NOT have yet.\n"
        "- Write only what is NEW in your source compared with them. Do not repeat their "
        "facts; if one is needed for context, give it in a few words, not a sentence.\n"
        "- Every fact still comes from your source. If little in it is new, write a short "
        "post: one or two lines is right. Never fill the gap with anything the source does "
        "not say.\n"
        "- Do not introduce the product as if for the first time (\"X launched Y\", \"Y is a "
        "new AI that...\"). The reader already knows what it is: name it and go straight to "
        "the new part.\n"
        "- You may point back once, naturally, by what it is (\"Meta's Muse Wonder\"), "
        "never with \"as we reported\" or \"in our previous post\".\n"
        "- Do not reuse their words. A different first line, different verbs, different "
        "sentence shapes, a differently worded link line. Side by side, the posts must read "
        "like one person writing a fresh update, not the same template filled in again.\n"
        "- If a post above turns out to be about a different product, ignore it."
    )


def _lines(html: str) -> list[list[str]]:
    """Each visible line as lowercase words; a phrase never runs from one line into the next."""
    text = persona_loader.visible_text(html).lower()
    return [words for line in text.splitlines() if (words := _WORD.findall(line))]


def shared_phrases(post: str, earlier: list[str]) -> list[str]:
    """Runs of PHRASE_WORDS or more words the post repeats from an earlier post, longest form."""
    seen = set()
    for text in earlier:
        for words in _lines(text):
            seen.update(tuple(words[i:i + PHRASE_WORDS])
                        for i in range(len(words) - PHRASE_WORDS + 1))
    found = []
    for words in _lines(post):
        hits = [i for i in range(len(words) - PHRASE_WORDS + 1)
                if tuple(words[i:i + PHRASE_WORDS]) in seen]
        spans: list[list[int]] = []
        for i in hits:
            if spans and i <= spans[-1][1]:
                spans[-1][1] = i + PHRASE_WORDS
            else:
                spans.append([i, i + PHRASE_WORDS])
        found += [" ".join(words[start:end]) for start, end in spans]
    return found
