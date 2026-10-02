"""Configuration that makes this the markets channel. Shared machinery (nodes/, brain/, utils/) knows none of this.
Beside this file: persona.md holds the voice, rubric.md defines importance.
To add a channel, copy this folder and change these values."""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent

NAME = "markets"

DB_FILENAME = "markets.db"

LOG_FILENAME = "markets.log"

BOT_TOKEN_KEY = "TELEGRAM_BOT_TOKEN"
CHANNEL_ID_KEY = "CHANNEL_ID"

PERSONA_PATH = HERE / "persona.md"
RUBRIC_PATH = HERE / "rubric.md"

# The image analyst judges every picture; clips go out unchecked, as before.
IMAGE_RUBRIC_PATH = HERE / "image_rubric.md"

MIN_IMPORTANCE = 4

# MUST match rubric.md: the provider enforces this list, so a topic the rubric
# asks for and this tuple omits is one the model physically cannot give. That
# mismatch silently mislabelled a hundred items.
TOPICS = ("crypto", "markets", "geopolitics", "other")

MARKETS = ("crypto", "rates_fx", "energy", "commodities", "equities",
           "risk_sentiment", "none")

# "other" is absent on purpose: it is the answer that means "reject".
VALID_TOPICS = ("crypto", "markets", "geopolitics")

SOURCES = [
    # ── Crypto ──
    {"name": "coindesk",       "topic": "crypto", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
    {"name": "theblock",       "topic": "crypto", "url": "https://www.theblock.co/rss.xml"},
    {"name": "protos",         "topic": "crypto", "url": "https://protos.com/feed"},
    {"name": "glassnode_research", "topic": "crypto", "url": "https://research.glassnode.com/rss/"},
    {"name": "unchained",      "topic": "crypto", "url": "https://unchainedcrypto.com/feed/"},
    {"name": "therage",        "topic": "crypto", "url": "https://www.therage.co/rss/"},

    # ── Geopolitics ──
    {"name": "guardian_world", "topic": "geopolitics", "url": "https://www.theguardian.com/world/rss"},
]

# Adding an account also needs trading/infra/tweet-relay/accounts.txt and a
# relay restart. Removing it here alone mutes it for this channel only.
X_ACCOUNTS = {
    "WatcherGuru":   "crypto",
    "crypto_banter": "crypto",
    "TreeNewsFeed":  "crypto",
    "BLS_gov":       "markets",      # payrolls, CPI — the data itself, not politics

    # Added 28 Aug 2026, all four already tracked by the relay.
    "glassnode":     "crypto",       # on-chain analytics
    "BullTheoryio":  "markets",      # indices, FX, yields, the Fed, some crypto
    "DeItaone":      "markets",      # Walter Bloomberg — central banks, results
    "Barchart":      "markets",      # equities, metals, commodities
}

NO_MEDIA_SOURCES = {"crypto_banter"}

USE_ECONOMIC_CALENDAR = True

# The stations, in order. A channel needing one of its own adds it to STAGES
# from channels/<name>/nodes.py and names it here; routing is shared.
PIPELINE = [
    "dedup",
    "sorter",
    "fetch_article",
    "story_organizer",
    "gatekeeper",
    "writer",
    "editor",
    "repeat_check",
    "image_analyst",
    "publish",
]
