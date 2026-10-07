"""Rewrites a story into the channel's single house style, because every source
writes differently. The prompt is prompts/writer.md, with the voice from
prompts/persona.md in front of it; code then guarantees what the prompt only asks
for (no emoji, a one-line source stays one line, no repeated openings).
It returns HTML, not JSON.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import config
from utils import logger as log_setup, openrouter

log = log_setup.get("writer")

# AI config: edit for writing style tuning.
MODEL = config.WRITER_MODEL
TEMPERATURE = 0.2  # Low: house style should stay consistent.
MAX_TOKENS = 900

# Ask for length, not write-long-then-cut (cuts mid-sentence).
LENGTH_RULE_TEXT = "70-100 words. Three short paragraphs at most."

# Telegram caps image captions at 1024 (vs 4096 for text).
LENGTH_RULE_IMAGE = (
    "45-65 words. This one is going out as a caption under a picture, and "
    "Telegram cuts captions off at 1024 characters, so it MUST be short. "
    "Two short paragraphs at most."
)

# Short X posts have no padding material; padding = inventing.
LENGTH_RULE_BRIEF = (
    "As short as the news. Often that is ONE line — the bold headline alone, "
    "and nothing under it. Never more than 45 words.\n"
    "\n"
    "The source here is only a couple of sentences long, so there is very "
    "little to work with. Report exactly what it says and STOP.\n"
    "\n"
    "EVERY FACT IN YOUR POST MUST APPEAR IN THE SOURCE TEXT. If the source "
    "gives you one fact, your post contains one fact. Do NOT add casualty "
    "figures, dates, place names, quantities, causes, reactions, or "
    "consequences that are not written in the source — not even ones you are "
    "confident are true from your own knowledge. You are reporting this "
    "specific source, not the event.\n"
    "\n"
    "Do NOT add background, context, implications, or a closing line to make "
    "the post feel more substantial. If you find yourself writing a sentence "
    "that is not traceable to a specific phrase in the source, delete it.\n"
    "\n"
    "A two-line post that is entirely true is a success. A longer one with a "
    "single invented detail is a failure that gets the whole post thrown away."
)

def _build_emoji_rule() -> str:
    """The mark rule: none at all, or one from a short list in config.POST_MARKS."""
    if not config.POST_MARKS:
        return (f"none. This channel uses no emoji at all, anywhere. The only symbol "
                f"allowed is the list bullet {config.BULLET}. Any emoji is deleted "
                f"automatically.")
    marks = "\n".join(f"  {mark} — {meaning}"
                      for mark, meaning in config.POST_MARKS.items())
    return (
        "ONE mark at the VERY START of the post, before the opening <b> tag, "
        "followed by a single space. Nowhere else.\n"
        "\n"
        "The mark says WHAT KIND of news this is. Pick from this list, by the "
        f"meaning given:\n{marks}\n"
        "\n"
        "Nothing fits cleanly: no mark. Better none than a wrong one. A mark that "
        "is not on this list, or a second one, is deleted automatically."
    )


EMOJI_RULE = _build_emoji_rule()


def _today() -> str:
    """Today's date for prompt; makes "this year" resolvable and guards against stale
    titles.
    """
    return datetime.now(timezone.utc).strftime("%d %B %Y")

PROMPT = config.WRITER_PROMPT_PATH.read_text()

# The line the publisher fills with the product link (see nodes/publisher.py).
LINK_PLACEHOLDER = 'href="LINK"'


_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")

# Models sometimes open with a sentence about what they're about to do, despite
# being told not to. These are the openings seen in practice.
_PREAMBLE = re.compile(
    r"^\s*(here'?s?|here is|sure|certainly|of course|okay|ok)\b[^\n]{0,80}[:\n]",
    re.IGNORECASE,
)

# Used to spot a post that was cut off in the middle.
_SENTENCE_ENDS = (".", "!", "?", '"', "'", ")", "”", "’", ">")

# Tags Telegram accepts. Anything else makes it reject the entire message.
_ALLOWED_TAGS = ("b", "i", "u", "s", "a", "code", "pre", "em", "strong",
                 "del", "ins", "strike", "blockquote", "tg-spoiler")


def _clean(text: str) -> str:
    """Strip code fences, preambles and stray whitespace from the model's reply."""
    cleaned = _FENCE.sub("", (text or "").strip())
    cleaned = _PREAMBLE.sub("", cleaned).strip()

    # Models occasionally wrap the whole post in quotes.
    if len(cleaned) > 2 and cleaned[0] == '"' and cleaned[-1] == '"':
        cleaned = cleaned[1:-1].strip()

    # Collapse runs of three or more blank lines down to one.
    return re.sub(r"\n{3,}", "\n\n", cleaned)


def _looks_incomplete(text: str) -> bool:
    """True if post cut off mid-sentence (models don't signal this; check text)."""
    stripped = text.rstrip()
    if not stripped:
        return True
    # A closing "Try it here" link line is not a sentence; judge what comes before it.
    lines = stripped.splitlines()
    if len(lines) > 1 and LINK_PLACEHOLDER in lines[-1]:
        stripped = "\n".join(lines[:-1]).rstrip()
    # Ignore a trailing HTML tag when looking at the final character.
    without_tag = re.sub(r"<[^>]+>\s*$", "", stripped).rstrip()
    if not without_tag:
        return True
    # A post that is only its headline is complete by design. Headlines do not
    # end in a full stop, so the check below would throw every one of them away.
    if re.fullmatch(r"[^<]{0,4}<b>[^<]{8,}</b>\s*", stripped):
        return False
    # A list item is a line, not a sentence; it rarely ends in a full stop.
    if stripped.splitlines()[-1].startswith(config.BULLET):
        return False
    return not without_tag.endswith(_SENTENCE_ENDS)


def _has_forbidden_tags(text: str) -> list[str]:
    """Return any HTML tags Telegram won't accept. Empty list means it's fine."""
    found = re.findall(r"</?([a-zA-Z][a-zA-Z0-9-]*)", text)
    return sorted({tag.lower() for tag in found if tag.lower() not in _ALLOWED_TAGS})


# Narrow: preserve accented letters, currency, dashes, quotes.
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF"     # pictographs, symbols, flags, transport
    "☀-➿"              # miscellaneous symbols and dingbats
    "⬀-⯿"              # arrows and misc symbols
    "←-⇿"              # arrows
    "✀-➿]"             # dingbats
    "|[︀-️‍⃣]"   # variation selectors, joiners, keycaps
)


def strip_emojis(text: str) -> str:
    """Remove every emoji and tidy gaps; "attack ⚡." → "attack." not "attack ."."""
    # Bullet is emoji by encoding but layout by intent; hide/strip/restore else lists
    # break.
    text = text.replace(config.BULLET, "\x00")
    cleaned = _EMOJI.sub("", text or "")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)            # "a  b"   -> "a b"
    cleaned = re.sub(r" +([.,!?;:])", r"\1", cleaned)       # "a ."    -> "a."
    cleaned = re.sub(r" +(</)", r"\1", cleaned)             # "a </b>" -> "a</b>"
    cleaned = re.sub(r"(?m)^[ \t]+", "", cleaned)           # line-leading spaces
    cleaned = re.sub(r"(?m)[ \t]+$", "", cleaned)           # line-trailing spaces
    return cleaned.strip().replace("\x00", config.BULLET)


# Models write ⚖️ and ⚖ interchangeably; accept both, store canonical.
_VARIATION_SELECTOR = "️"
_FLAG = re.compile("[\U0001F1E6-\U0001F1FF]{2}")


def enforce_mark(text: str) -> tuple[str, str]:
    """Keep one approved leading mark; remove all other emoji. Return (text, mark)."""
    text = (text or "").lstrip()

    # Model told to put mark BEFORE <b>, half the time puts it inside; read both.
    leading_tag = ""
    if text.startswith("<b>"):
        leading_tag, text = "<b>", text[3:].lstrip()

    mark = ""
    for candidate in config.POST_MARKS:
        for spelling in (candidate, candidate.replace(_VARIATION_SELECTOR, "")):
            if spelling and text.startswith(spelling):
                mark = candidate                      # store the canonical form
                text = text[len(spelling):].lstrip()
                break
        if mark:
            break

    # A country's flag: two regional-indicator symbols. Any pair is a flag, so
    # the list in config cannot enumerate them; the shape is enough.
    if not mark and config.ALLOW_FLAG_MARKS:
        flag = _FLAG.match(text)
        if flag:
            mark = flag.group(0)
            text = text[len(mark):].lstrip()

    cleaned = strip_emojis(leading_tag + text)
    # Whatever was stripped from inside the tag must not leave a gap behind.
    cleaned = re.sub(r"<b>\s+", "<b>", cleaned)
    if not cleaned or cleaned == "<b>":
        return "", ""
    return (f"{mark} {cleaned}" if mark else cleaned), mark


# One-line source can't support one-line post. Below 32 words: body is headline again or
# invented (models caught on both).
ONE_LINE_SOURCE_WORDS = 32


def is_one_line_source(item) -> bool:
    """True if the source is a single sentence — a bare wire headline."""
    text = f"{item['title'] or ''} {item['body'] or ''}"
    words = {w for w in re.findall(r"[a-z0-9$%.]+", text.lower()) if len(w) > 1}
    return len(words) <= ONE_LINE_SOURCE_WORDS


def link_line_last(post: str) -> str:
    """Move the href="LINK" line to the very end, where the reader expects it."""
    blocks = re.split(r"\n\s*\n", post.strip())
    links = [b for b in blocks if LINK_PLACEHOLDER in b]
    if len(links) != 1 or blocks[-1] == links[0]:
        return post
    return "\n\n".join([b for b in blocks if b != links[0]] + links)


def _opening(text: str, words: int = 2) -> str:
    """The first words of a post's first line, lowercased, without tags or punctuation."""
    first = re.sub(r"<[^>]+>", "", (text or "").strip().split("\n", 1)[0])
    first = first.replace("’", "'").lower()
    return " ".join(re.findall(r"[a-z0-9']+", first)[:words])


def repeated_opening(post: str, recent_posts: list[str], window: int = 10) -> str:
    """The recent post whose first two words this post repeats, or "" if none does."""
    mine = _opening(post)
    if not mine:
        return ""
    for earlier in recent_posts[:window]:
        if _opening(earlier) == mine:
            return earlier.split("\n", 1)[0][:120]
    return ""


def headline_only(post: str) -> str:
    """Cut a post down to its first line — the mark and the bold headline."""
    first = post.strip().split("\n", 1)[0].strip()
    return first if "<b>" in first else post


def _figures(text: str) -> set[str]:
    """Every number in a text, commas dropped, so 486,532 and 486532 match."""
    return {n.replace(",", "") for n in re.findall(r"\d[\d,.]*\d|\d", text)}


def figures_lost_by_cut(item, post: str) -> set[str]:
    """Source figures the body carries that the headline alone would drop.

    "TESLA 3Q DELIVERIES 486,532, EST. 463,761" was cut to "Tesla Q3 deliveries:
    486,532" — the estimate, the only thing that made the number mean anything, went.
    """
    source = _figures(f"{item['title'] or ''} {item['body'] or ''}")
    return (_figures(post) - _figures(headline_only(post))) & source


def _stems(text: str) -> set[str]:
    """Content words cut to five letters, so "plans" matches "plan" and "games" "game"."""
    return {w[:5] for w in re.findall(r"[a-z]{4,}", re.sub(r"<[^>]+>", " ", text.lower()))
            if w not in _COMMON}


_COMMON = {"that", "this", "with", "from", "your", "their", "they", "there", "then", "than",
           "what", "when", "will", "have", "been", "were", "also", "into", "more", "most",
           "while", "which", "about", "just", "only", "here", "read", "link", "href"}


def lost_by_cut(item, post: str) -> set[str]:
    """What cutting to the headline would throw away that came from the source: its figures,
    and any body sentence whose words are mostly the source's ("Users on paid plans can
    generate" went with the Playground post's headline-only cut). Padding still goes."""
    lost = figures_lost_by_cut(item, post)
    source = _stems(f"{item['title'] or ''} {item['body'] or ''}")
    body = post.strip().split("\n", 1)[1] if "\n" in post.strip() else ""
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", body):
        words = _stems(sentence)
        if len(words) >= 4 and len(words & source) / len(words) >= 0.6:
            lost.add(sentence.strip()[:60])
    return lost


def has_thin_source(item) -> bool:
    """True if barely any source material; decides post length (can't write 90w from 150c
    summary).
    """
    return len((item["body"] or "").strip()) < config.BRIEF_SOURCE_CHARS


def is_brief(item) -> bool:
    """True if this is a short X post. Only used by the rehearsal tools now."""
    return item["origin"] == "x" and has_thin_source(item)


async def execute(item, has_image: bool = False, editor_feedback: str = "",
                  recent_posts: list[str] | None = None, persona: str = "",
                  brief: str = "") -> str:
    """Write post; return Telegram HTML or "" (never "publish nothing"). editor_feedback:
    rewrite reason; recent_posts: channel history; brief: what's new/known; persona:
    prompts/persona.md.
    """

    title = item["title"] or ""
    body = (item["body"] or "")[: config.MAX_BODY_CHARS]
    origin = "a post on X" if item["origin"] == "x" else "a news article"

    user_message = (
        f"Source: {item['source_name']} ({origin})\n"
        f"Topic: {item['topic'] or item['topic_hint']}\n\n"
        f"Headline: {title}\n\n"
        f"Text:\n{body}"
    )

    if editor_feedback:
        user_message += (
            f"\n\n---\nREWRITE REQUEST\n"
            f"The channel editor rejected your previous draft of this post for "
            f"this specific reason: {editor_feedback}\n"
            f"Write the post again, fixing exactly that problem. Do not change "
            f"anything else about how you follow the rules above."
        )

    # LENGTH by source material, not origin. Conflating sent 150c down 90w path →
    # invented "organized crime rings".
    thin = has_thin_source(item)

    if thin:
        length_rule = LENGTH_RULE_BRIEF
    elif has_image:
        length_rule = LENGTH_RULE_IMAGE
    else:
        length_rule = LENGTH_RULE_TEXT

    system_prompt = PROMPT.format(length_rule=length_rule, emoji_rule=EMOJI_RULE,
                                  today=_today())

    # Persona = voice only; factual-accuracy rules above override it.
    if persona.strip():
        system_prompt = f"{persona}\n\n---\n\n{system_prompt}"

    # One heading over two: voice examples + what reader read. Old wording (voice only)
    # caused model to match shape and change number (4 yields, same skeleton).
    if recent_posts and config.VARY_WRITING:
        examples = "\n\n".join(
            f"Post {i + 1}:\n{p}" for i, p in enumerate(recent_posts[:10])
        )
        system_prompt += (
            "\n\n---\nTHE CHANNEL'S LAST POSTS (newest first)\n\n"
            "One person writes this channel, and a person does not repeat themselves. "
            "Do NOT start your post the way any of these start, do not reuse their "
            "phrases (\"Here's a\", \"It's a\", \"It's called\"), and do not copy their "
            "structure: if most of them use • lines, use a short paragraph, and the "
            "other way round. Your reader has also just read them, so do not repeat "
            "their facts as part of your story.\n\n"
            f"{examples}"
        )
    if brief:
        system_prompt += f"\n\n---\n{brief}"

    try:
        raw = await openrouter.chat_text(
            model=MODEL, system=system_prompt, user=user_message,
            temperature=TEMPERATURE, max_tokens=MAX_TOKENS,
        )
    except Exception as error:  # noqa: BLE001
        log.warning("Writer failed for item %s: %s", item["id"], error)
        return ""

    post = _clean(raw)

    if not post:
        log.warning("Writer returned nothing for item %s", item["id"])
        return ""

    # A person would not open two posts in a row the same way. One more try.
    echoed = repeated_opening(post, recent_posts or []) if config.VARY_WRITING else ""
    if echoed:
        log.info("Item %s opens like a recent post (%s) — asking for another opening",
                 item["id"], echoed[:60])
        try:
            again = _clean(await openrouter.chat_text(
                model=MODEL, system=system_prompt,
                user=user_message + (
                    f"\n\n---\nYour draft opened the same way as a recent post: \"{echoed}\". "
                    f"Write it again with a different first line and different wording. "
                    f"Your previous draft:\n{post}"),
                temperature=TEMPERATURE + 0.2, max_tokens=MAX_TOKENS))
            if again and not repeated_opening(again, recent_posts or []):
                post = again
        except Exception as error:  # noqa: BLE001 - the first draft still stands
            log.info("Second opening for item %s failed: %s", item["id"], error)

    # Prompt not enough; guarantee it.
    before = post
    post, mark = enforce_mark(post)
    if post != before:
        log.info("Tidied the marks on item %s — kept %s", item["id"], mark or "none")

    # One-fact source = one-line post (prompt says so, model adds body anyway, editor
    # waves it). Guaranteed, not requested.
    if is_one_line_source(item) and "\n" in post.strip():
        lost = lost_by_cut(item, post)
        if lost:
            log.info("Item %s has a one-line source, but the body carries source facts "
                     "the headline lacks (%s) — kept it", item["id"], " | ".join(sorted(lost)))
        else:
            post = headline_only(post)
            log.info("Item %s has a one-line source — kept the headline only", item["id"])

    if config.LINK_TO_PRODUCT:
        post = link_line_last(post)

    if _looks_incomplete(post):
        log.warning("Writer produced a post that stops mid-sentence for item %s — "
                    "discarding it rather than publishing half a thought", item["id"])
        return ""

    forbidden = _has_forbidden_tags(post)
    if forbidden:
        # Not fatal (telegram_html strips them), but logged to spot misbehaving models.
        log.info("Writer used tags Telegram doesn't allow %s on item %s — "
                 "they will be stripped before sending", forbidden, item["id"])

    return post
