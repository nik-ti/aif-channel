"""Decides which of a story's waiting items a finished post actually covered.

Before this existed, every item waiting on a story was marked covered the moment
the story posted, whether the post mentioned it or not. Two real cases: a post
about Brent crude falling $3 "covered" an item saying Trump had rejected a
ceasefire, and a post about Fed governor Barr "covered" the item carrying the
month's PCE inflation figure. Both facts vanished with the mark that claimed
they had been told.

No model is asked. A model shown six items tends to report all six as used
simply because it saw them, so the question is answered from the text instead:
an item counts as covered when the post repeats something only THAT item brought
to the story. Distinctive is measured against the story's other items, because
inside one story every item shares the subject — "Trump" and "Iran" appear in
all of them and prove nothing.

An item that brought nothing its siblings did not is counted as covered: there is
no fact left for the reader to miss. Everything else stays waiting, which is the
safe direction — a repeated item is an embarrassment, a silently buried one is a
story the channel never told.

Checked against six hand-labelled pairs from this channel's own history and
correct on all six.
"""

from __future__ import annotations

import re

# A figure worth checking. A single digit counts only when a currency sign, a
# percent sign or a decimal point pins it down: "$3 a barrel" and "2% target"
# are facts, the 3 in "3 minutes" is noise.
FIGURE = re.compile(r"""
    \$\s?\d[\d,]*\.?\d*        |   # $3, $530, $5.59
    \d[\d,]*\.?\d*\s?%         |   # 2%, 5.59%
    \d[\d,]*\.\d+              |   # any decimal
    \d[\d,]{1,}                    # two digits or more
""", re.X)

WORD = re.compile(r"[A-Za-z][A-Za-z'-]{3,}")

# Words too common to prove anything, including the wire's own furniture.
STOP = frozenset({
    "this", "that", "with", "from", "have", "has", "been", "were", "was", "will",
    "would", "said", "says", "also", "after", "before", "about", "into", "over",
    "than", "then", "they", "their", "them", "there", "these", "those", "which",
    "while", "when", "what", "more", "most", "some", "such", "only", "just",
    "other", "both", "each", "its", "his", "her", "our", "your", "not", "but",
    "for", "and", "the", "are", "per", "cent", "percent", "year", "years",
    "month", "months", "week", "weeks", "day", "days", "time", "times",
    "according", "reported", "report", "data", "news", "update", "level",
    "levels", "https", "http", "amid",
})


def _tokens(text: str) -> set[str]:
    """The checkable facts in a piece of text: its figures and its rarer words."""
    text = text or ""
    figures = {f.replace(" ", "").replace(",", "").rstrip(".")
               for f in FIGURE.findall(text)}
    words = {w.lower() for w in WORD.findall(text)}
    return figures | (words - STOP)


def item_text(item) -> str:
    """One item's words, for comparison. Title and body, nothing else."""
    return f"{item['title'] or ''}\n{item['body'] or ''}"


def covered_by(post_text: str, candidate, others: list) -> tuple[bool, str]:
    """(True, why) when `post_text` repeats a fact only `candidate` supplied."""
    mine = _tokens(item_text(candidate))
    theirs: set[str] = set()
    for other in others:
        theirs |= _tokens(item_text(other))

    distinctive = mine - theirs
    if not distinctive:
        return True, "it added nothing the story's other items did not"

    landed = distinctive & _tokens(post_text)
    if landed:
        shown = ", ".join(sorted(landed)[:6])
        return True, f"the post repeats its own detail: {shown}"
    return False, "the post does not carry any of its own details"


def split_by_coverage(post_text: str, waiting: list, trigger
                      ) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Sort a story's waiting items into (covered, still waiting).

    `trigger` is the item the post is filed under and is the post's main source,
    so it always belongs in the comparison even though it is never a candidate.
    Leaving it out was a real bug: a post written from "Trump says he offered
    Iran nothing" made the word "Trump" look like the distinctive contribution
    of a sibling item about Trump rejecting a ceasefire, and buried it.
    """
    trigger_id = trigger["id"] if trigger is not None else None
    covered: list[tuple[int, str]] = []
    left: list[tuple[int, str]] = []
    for candidate in waiting:
        if candidate["id"] == trigger_id:
            continue
        others = [o for o in waiting if o["id"] != candidate["id"]]
        if trigger is not None and trigger_id not in {o["id"] for o in others}:
            others = others + [trigger]
        yes, why = covered_by(post_text, candidate, others)
        (covered if yes else left).append((candidate["id"], why))
    return covered, left
