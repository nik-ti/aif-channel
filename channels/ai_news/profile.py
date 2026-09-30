"""The AI news channel skeleton (not yet filled in). See channels/markets/profile.py for the worked example.
Shared machinery (nodes/, brain/, utils/) needs no changes; what belongs here is only what makes this channel different.
Still to decide: rubric.md (what it covers), persona.md (voice), sources, and any channel-specific stations in PIPELINE."""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent

NAME = "ai_news"

DB_FILENAME = "ai-news.db"
LOG_FILENAME = "ai-news.log"

# Its own bot and its own channel, so its own .env keys.
BOT_TOKEN_KEY = "AI_TELEGRAM_BOT_TOKEN"
CHANNEL_ID_KEY = "AI_CHANNEL_ID"

PERSONA_PATH = HERE / "persona.md"
RUBRIC_PATH = HERE / "rubric.md"

MIN_IMPORTANCE = 4

# Placeholders. The markets channel's third axis is "which market reprices",
# which is the wrong question here — what replaces it is part of writing the
# rubric, and the schema is built from whatever these say.
TOPICS = ("other",)
MARKETS = ("none",)
VALID_TOPICS = ("other",)

SOURCES: list[dict] = []
X_ACCOUNTS: dict[str, str] = {}
NO_MEDIA_SOURCES: set[str] = set()

# The economic calendar is a markets thing.
USE_ECONOMIC_CALENDAR = False

# The same stations as the markets channel for now. A media-reading station
# would slot in after fetch_article, once it exists in nodes.py beside this file.
PIPELINE = [
    "dedup",
    "sorter",
    "fetch_article",
    "story_organizer",
    "gatekeeper",
    "writer",
    "editor",
    "repeat_check",
    "publish",
]
