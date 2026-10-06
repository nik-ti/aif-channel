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

# Without today's date the sorter took "August 2026 payrolls" for a forecast and dropped it.
SORTER_SHOWS_DATE = True

# Measured 2026-10-06 against the old pair (gemini-2.5-flash sorter, deepseek-v3.2 writer).
# Sorter, 200 past items + 50 repeats: 100% schema, agreed with nikita's labels 43/49
# (old 40/49), let 1 of 14 known rumours/small items through (old 5), ~$3/month, 0.7s.
# Only Claude Sonnet 5.5 matched it, at $32/month. Served by Google alone.
SORTER_MODEL = "google/gemini-3.5-flash-lite"
# Writer, 40 past posts judged by the live editor: 31/40 approved (old 24/40), one post
# with a figure not in its source (old 2), ~$0.0003 a post. Posts run ~20% shorter.
# A different lab from the editor (Mistral), as EDITOR_FALLBACK_MODEL's rule requires.
# It declares no `temperature`; chat_text sends one and OpenRouter accepts it.
WRITER_MODEL = "openai/gpt-6-luna"

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
