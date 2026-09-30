"""Matches a news item to a scheduled release from ForexFactory, which supplies the
forecast and the previous reading.

That lets the sorter know the item is official, the writer add the numbers, and
the editor check them against the source. Matching is deliberately dumb —
country, a keyword in the title, and a time window — because fuzzy matching tied
every mention of the Fed to a scheduled Fed speech.

It fails open: no feed means the item passes through unchanged.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

import config
from utils import db, logger as log_setup

log = log_setup.get("calendar")

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# The feed names a release one way and the wire another. Each entry: words
# that identify the release in a feed title -> words that identify it in an
# item. Both sides lower-case. A release matches when one word from each side
# is present.
_ALIASES: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("cpi",),                       ("cpi", "consumer price", "inflation")),
    (("core cpi",),                  ("core cpi", "core inflation")),
    (("ppi",),                       ("ppi", "producer price")),
    (("non-farm", "nonfarm"),        ("payroll", "nfp", "nonfarm", "non-farm", "jobs report")),
    (("unemployment claims",),       ("jobless claims", "initial claims", "unemployment claims")),
    (("unemployment rate",),         ("unemployment rate", "jobless rate")),
    (("retail sales",),              ("retail sales",)),
    (("gdp",),                       ("gdp", "gross domestic")),
    # The decision itself, not the day. "Fed" alone would attach the rate
    # forecast to every remark the chair makes for three hours afterwards.
    (("federal funds rate",),        ("raises rates", "cuts rates", "holds rates", "rate decision",
                                      "raises interest rates", "cuts interest rates", "bps to",
                                      "basis points to", "fed funds", "target range")),
    (("fomc economic projections",), ("dot plot", "projections", "median forecast")),
    (("fomc statement",),            ("fomc statement", "fed statement", "statement says")),
    (("press conference",),          ("press conference",)),
    (("boj policy rate",),           ("boj", "bank of japan")),
    (("official bank rate",),        ("boe", "bank of england")),
    (("main refinancing rate", "ecb"), ("ecb", "european central bank", "lagarde")),
    (("pmi",),                       ("pmi",)),
    (("crude oil inventories",),     ("crude inventories", "oil inventories", "eia")),
    # Added 2026-09-30. The channel had run two months with no PCE entry at all,
    # so the Fed's preferred inflation gauge could never match its own release:
    # on 30 September the calendar held "Core PCE Price Index m/m" with a 0.3%
    # forecast and six items about that print matched nothing, while one of them
    # attached itself to Final GDP because it mentioned GDP in passing.
    (("pce",),                       ("pce", "personal consumption")),
    (("core pce",),                  ("core pce",)),
    (("consumer confidence",),       ("consumer confidence",)),
    (("jolts", "job openings"),      ("jolts", "job openings")),
    (("adp",),                       ("adp",)),
    (("durable goods",),             ("durable goods",)),
    (("ism",),                       ("ism",)),
    (("trade balance",),             ("trade balance", "trade deficit")),
    (("housing starts",),            ("housing starts",)),
    (("building permits",),          ("building permits",)),
    (("industrial production",),     ("industrial production",)),
    (("consumer sentiment",),        ("consumer sentiment", "michigan")),
]

# The feed's currency code, and how the wire names that economy.
_COUNTRY_WORDS = {
    "USD": ("us ", "u.s.", "united states", "fed", "fomc", "american", "🇺🇸"),
    "EUR": ("euro", "ecb", "eurozone", "🇪🇺"),
    "GBP": ("uk ", "u.k.", "britain", "british", "boe", "bank of england", "🇬🇧"),
    "JPY": ("japan", "boj", "🇯🇵"),
    "CNY": ("china", "chinese", "pboc", "🇨🇳"),
    "CAD": ("canada", "canadian", "🇨🇦"),
    "AUD": ("australia", "rba", "🇦🇺"),
    "CHF": ("swiss", "snb", "🇨🇭"),
}

# A release is a moment. The number is reported within the hour; after that
# the wire is carrying reaction and commentary, which must not inherit the
# forecast. A preview can arrive a little early.
_AFTER = timedelta(minutes=45)
_BEFORE = timedelta(minutes=15)


async def refresh() -> int:
    """Pull this week's feed into the calendar table. Returns rows stored."""
    try:
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "Mozilla/5.0"}) as client:
            response = await client.get(FEED_URL)
            response.raise_for_status()
            events = response.json()
    except Exception as error:  # noqa: BLE001
        log.warning("Could not fetch the economic calendar: %s", error)
        return 0

    rows = []
    for e in events:
        if e.get("impact") not in ("High", "Medium"):
            continue
        try:
            at = datetime.fromisoformat(e["date"]).astimezone(timezone.utc)
        except (KeyError, ValueError):
            continue
        rows.append((e.get("country", ""), e.get("title", ""), at.strftime("%Y-%m-%d %H:%M:%S"),
                     e.get("impact", ""), e.get("forecast") or "", e.get("previous") or ""))

    db.replace_calendar(rows)
    log.info("Calendar refreshed: %d High/Medium releases this week", len(rows))
    return len(rows)


def match(text: str, when: datetime, headline: str = "") -> dict | None:
    """The scheduled release this item is about, or None.

    `when` is when the item arrived. Candidates are releases whose time is within
    a short window of it, for an economy the text names, whose title the text
    refers to. A release named in the item's HEADLINE beats one mentioned only in
    passing further down, and only then does the nearest in time win. That order
    matters: an item headlined "softer US inflation" also mentioned a GDP
    revision three lines later and was filed under Final GDP.
    """
    lowered = f" {text.lower()} "
    head = f" {headline.lower()} " if headline else ""
    since = (when - _AFTER).strftime("%Y-%m-%d %H:%M:%S")
    until = (when + _BEFORE).strftime("%Y-%m-%d %H:%M:%S")

    candidates = list(db.calendar_between(since, until))
    titles = {row["title"].lower() for row in candidates}

    best, best_rank = None, None
    for row in candidates:
        country_words = _COUNTRY_WORDS.get(row["country"])
        if not country_words or not any(w in lowered for w in country_words):
            continue
        title = row["title"].lower()
        hits = [item_words for feed_words, item_words in _ALIASES
                if any(f in title for f in feed_words)
                and any(i in lowered for i in item_words)]
        if not hits:
            continue
        # "Core Retail Sales" and "Retail Sales" share a slot, so the core row is
        # only the match when the item says "core" — but ONLY when the plain row
        # is actually there to take it instead. On 30 September the calendar held
        # Core PCE and no headline PCE, and this rule silently threw away every
        # item that just said "US PCE came in at 3.4%".
        if "core" in title and "core" not in lowered:
            plain = title.replace("core ", "").strip()
            if plain in titles:
                continue
        in_headline = bool(head) and any(i in head for words in hits for i in words)
        gap = abs((when - datetime.fromisoformat(row["at_utc"])
                   .replace(tzinfo=timezone.utc)).total_seconds())
        rank = (0 if in_headline else 1, gap)
        if best_rank is None or rank < best_rank:
            best, best_rank = row, rank

    return dict(best) if best is not None else None


def key_for(match: dict | None) -> str:
    """A stable name for one scheduled release, or "" when there is no match.

    NOT the calendar row's id: refresh() empties the table and re-inserts, so the
    ids change every few hours. Country, title and scheduled time do not.
    """
    if not match:
        return ""
    return f"{match['country']}|{match['title']}|{match['at_utc']}"


def describe(item) -> str:
    """The calendar line that goes into a prompt, or "" if the item matched nothing."""
    title = item["calendar_title"] if "calendar_title" in item.keys() else ""
    if not title:
        return ""
    parts = [f"Scheduled release: {title}"]
    if item["calendar_forecast"]:
        parts.append(f"forecast {item['calendar_forecast']}")
    if item["calendar_previous"]:
        parts.append(f"previous {item['calendar_previous']}")
    return ", ".join(parts)
