# Every setting for the channel. Secrets live in .env; everything else has a
# sensible default here and can be overridden in .env.
#
# Any name can be prefixed with the channel's own name to override it for that
# channel alone, for example AI_NEWS_MAX_POSTS_PER_HOUR.

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "schema.sql"

_ENV = dotenv_values(HERE / ".env")


# Set once CHANNEL is known; initially unprefixed so CHANNEL itself can be read.
_PREFIX = ""


def _get(name: str, default: str = "") -> str:
    """Read setting, preferring this channel's own value (shared vs. per-channel)."""
    for key in ((_PREFIX + name) if _PREFIX else "", name):
        if not key:
            continue
        value = _ENV.get(key) or os.environ.get(key)
        if value is not None:
            return value.strip()
    return default.strip()


def _get_int(name: str, default: int) -> int:
    """Read a whole-number setting."""
    try:
        return int(_get(name, str(default)))
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    """Read a decimal setting."""
    try:
        return float(_get(name, str(default)))
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    """Read an on/off setting. Anything but a recognised word keeps the default."""
    value = _get(name, "").lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


# CHANNEL SELECTION: two channels run from same code, told apart by CHANNEL in .env/unit
# file.

CHANNEL = _get("CHANNEL", "markets")
_PREFIX = CHANNEL.upper() + "_"

try:
    _profile = __import__(f"channels.{CHANNEL}.profile", fromlist=["profile"])
except ImportError as error:  # pragma: no cover - a typo here must be loud
    raise SystemExit(
        f"CHANNEL is '{CHANNEL}' but channels/{CHANNEL}/profile.py could not be "
        f"loaded: {error}\nChannels available: "
        f"{', '.join(sorted(p.parent.name for p in HERE.glob('channels/*/profile.py')))}"
    ) from error

CHANNEL_NAME = _profile.NAME

# Each channel has separate DB (avoid cross-channel duplicate checks and story layer).
DB_PATH = HERE / "data" / _profile.DB_FILENAME
LOG_PATH = HERE / "logs" / _profile.LOG_FILENAME

SOURCES = _profile.SOURCES
X_ACCOUNTS = _profile.X_ACCOUNTS
NO_MEDIA_SOURCES = _profile.NO_MEDIA_SOURCES
VALID_TOPICS = _profile.VALID_TOPICS
PERSONA_PATH = _profile.PERSONA_PATH
TOPICS = _profile.TOPICS
MARKETS = _profile.MARKETS
RUBRIC_PATH = _profile.RUBRIC_PATH
PIPELINE = _profile.PIPELINE
USE_ECONOMIC_CALENDAR = getattr(_profile, "USE_ECONOMIC_CALENDAR", False)


# SECRETS (from .env); key names are per-channel.

TELEGRAM_BOT_TOKEN = _get(_profile.BOT_TOKEN_KEY)
CHANNEL_ID = _get(_profile.CHANNEL_ID_KEY)   # "@name" or "-100..."
ERROR_CHAT_ID = _get("ERROR_CHAT_ID")    # your DM, for error alerts
OPENROUTER_API_KEY = _get("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = _get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")






# POST APPEARANCE: one mark per post at front (WRITER picks from list or flag).
# Fixed list prevents emoji misuse (🔥 on drone strike); marks signal what, not how to
# feel.
# No hashtags: two would sort posts by desk, not reader.

POST_MARKS = {
    # a number moving — the short, specific posts
    "🔺": "a price, yield or figure rising — the number is the news",
    "🔻": "a price, yield or figure falling — the number is the news",
    "📈": "a market or trend moving up over a period, or an expected rise",
    "📉": "a market or trend moving down over a period, or an expected fall",
    "📊": "a scheduled data release or official statistics",
    # institutions
    "🏛️": "a central bank, government or regulator deciding or projecting",
    "🏦": "a commercial bank, or the banking system",
    "⚖️": "a court ruling, charge, lawsuit or enforcement action",
    "📝": "a tax, a bill, a law — legislation moving",
    # money and markets
    "💵": "the dollar, dollar liquidity, or money in general; crypto too",
    "💴": "the yen or Japan's money",
    "💶": "the euro or the eurozone's money",
    "🛢️": "oil, gas, refining, pipelines",
    # risk
    "⚠️": "a hack, exploit, breach or security vulnerability",
    "🔒": "safety, custody, a freeze or a lock-up of funds or assets",
}

# Bullet for lists (only emoji allowed in body; strip_emojis protects it).
BULLET = "▪️"

# Country flags are valid marks when country is the story (250 of them; accept any
# flag).

# "markets" topic added 2026-08-28; bar unchanged in nodes/sorter.py.
# Short sources (X posts) become BRIEF posts to avoid invention.
BRIEF_SOURCE_CHARS = _get_int("BRIEF_SOURCE_CHARS", 400)


# WHAT GETS PUBLISHED: sorter scores 1-5 for impact; only >= MIN_IMPORTANCE published.
# Scale: 5=biggest events, 4=market-moving (recommended), 3=ordinary news, 1=everything.
# See nodes/sorter.py.
MIN_IMPORTANCE = _get_int("MIN_IMPORTANCE", _profile.MIN_IMPORTANCE)


# TIMING AND LIMITS

POLL_MINUTES = _get_int("POLL_MINUTES", 10)

# Tweet relay: TWEET_STREAM_GROUP must stay fixed (new name skips/re-reads); different
# from "sniper-ingest".
REDIS_URL = _get("REDIS_URL", "redis://localhost:6379/0")
TWEET_STREAM_KEY = _get("TWEET_STREAM_KEY", "tweets:stream")
TWEET_STREAM_GROUP = _get("TWEET_STREAM_GROUP", "news-channel")
X_MAX_AGE_MINUTES = _get_int("X_MAX_AGE_MINUTES", 45)  # Stop restart floods.
X_MAX_BURST = _get_int("X_MAX_BURST", 25)

# Stop old feeds replaying back catalogue on next poll.
ARTICLE_MAX_AGE_HOURS = _get_int("ARTICLE_MAX_AGE_HOURS", 24)

# Publishing pace
PUBLISH_TICK_SECONDS = _get_int("PUBLISH_TICK_SECONDS", 120)
MAX_POSTS_PER_TICK = _get_int("MAX_POSTS_PER_TICK", 2)
SECONDS_BETWEEN_SENDS = _get_int("SECONDS_BETWEEN_SENDS", 3)
MIN_SECONDS_BETWEEN_POSTS = _get_int("MIN_SECONDS_BETWEEN_POSTS", 90)
MAX_POSTS_PER_HOUR = _get_int("MAX_POSTS_PER_HOUR", 12)
MAX_POSTS_PER_DAY = _get_int("MAX_POSTS_PER_DAY", 60)

# Queue housekeeping: drop stale items to prevent queue growth and stale posts.
QUEUE_TTL_MINUTES = _get_int("QUEUE_TTL_MINUTES", 90)
MAX_QUEUE_SIZE = _get_int("MAX_QUEUE_SIZE", 200)
MAX_ATTEMPTS = _get_int("MAX_ATTEMPTS", 3)


# DUPLICATE DETECTION: five checks, cheapest first (see nodes/dedup.py).

# Check 3: headline similarity (0-100).
FUZZY_THRESHOLD = _get_int("FUZZY_THRESHOLD", 92)
FUZZY_WINDOW_HOURS = _get_int("FUZZY_WINDOW_HOURS", 24)

# Check 4: semantic similarity (0.0-1.0). Measured on 19 pairs: duplicates 0.738-0.993,
# different 0.785-0.900 (overlap).
# 0.72 caught 100% of duplicates; 0.75 missed some.
COSINE_SHORTLIST = _get_float("COSINE_SHORTLIST", 0.72)  # Check 5 decides between SHORTLIST and different stories.
COSINE_CERTAIN = _get_float("COSINE_CERTAIN", 0.95)  # Near-verbatim; merge without check 5.
COSINE_WINDOW_HOURS = _get_int("COSINE_WINDOW_HOURS", 48)

# How many candidates to compare (was 1, lost burst dedup).
DEDUP_TOP_K = _get_int("DEDUP_TOP_K", 3)

# TIME GATE: duplicates in sample landed within 10.1h; false merges 24h apart (recurring
# reports). Removes for free, before model runs.
DUPLICATE_MAX_GAP_HOURS = _get_int("DUPLICATE_MAX_GAP_HOURS", 12)

EMBEDDING_MODEL = _get("EMBEDDING_MODEL", "openai/text-embedding-3-small")

# AI MODELS: prompts live in node files, not here.

# 1. Sorter: scores importance/topic. ~$1.50/mo ($6.53 of $7.40 for gemini-2.5-flash, vs
# haiku $20 of $23).
# 88% of bill: 4529-token rubric, 142x/day. Prompt caching measured and REJECTED: cache
# read $0.000812 vs uncached $0.005091,
# but 5m expiry vs 6.5m median gap (only 41% <5m); miss costs $0.009909 → 21% DEARER.
SORTER_MODEL = _get("SORTER_MODEL", "google/gemini-2.5-flash")

# 2. Writer: deepseek-v3.2 $0.40/M vs Gemini $2.50/M; output-heavy, so halves pipeline
# cost.
WRITER_MODEL = _get("WRITER_MODEL", "deepseek/deepseek-v3.2")

# 3. Editor: checks post against source. Tested 7 pairs: MiniMax 7/7 at 2.5s, mistral
# 7/7, deepseek missed 1, qwen missed 3 at 32s.
# SWAPPED 2026-09-30: MiniMax failed 28/week (16 "ran out of room", 429/502/522);
# mistral fallback passed 7/7 instead.
# Claude-haiku-4.5 not used: accepts schema (4/4), but this node fails CLOSED catching
# falsehoods—need test pairs with known falsehoods.
EDITOR_MODEL = _get("EDITOR_MODEL", "mistralai/mistral-medium-3.1")

# Fallback when EDITOR unreachable (fails closed). MiniMax unreliable: 15 failures/2wks
# (10×429), cost 4 stories including BLS payrolls.
# Fallback must clear same bar: rubber-stamp worse than losing story. Tested 3 cases:
# mistral 1-2s all 3; qwen waved through falsehoods.
# Set "" to disable.
EDITOR_FALLBACK_MODEL = _get("EDITOR_FALLBACK_MODEL", "minimax/minimax-m2.7")

# Ceiling on editor call (retries+fallback). Worst: 3 retries × 2 models = 368s (3×
# publish tick). Normal: 2-4s.
EDITOR_TIMEOUT_SECONDS = _get_int("EDITOR_TIMEOUT_SECONDS", 60)

# Alerts you if the editor starts rejecting an unusual share of posts.
EDITOR_DECLINE_ALERT_RATE = _get_float("EDITOR_DECLINE_ALERT_RATE", 0.5)
EDITOR_DECLINE_WINDOW = _get_int("EDITOR_DECLINE_WINDOW", 20)

# A post rejected for a FIXABLE rule (see FIXABLE_RULES in brain/nodes.py) goes
# back to the writer with the reason instead of being dropped. Capped low: each
# loop costs another writer + editor call, and a third draft never makes it.
MAX_REWRITES = _get_int("MAX_REWRITES", 1)


# 4. Judge (dedup check 5): only step that tells "inflows" from "outflows". STABILITY >
# ACCURACY.
# Test 20 pairs: deepseek 80% (0 wrong merges, order-stable 6/6), gemini 75% (0 wrong,
# order-flips 3/6), minimax 13/20 failed concurrency.
# Measured 2026-09-30 on 40 real pairs: haiku 38/40, gemini 39/40, all 40/40 shape.
# Disagreements: haiku right (Kalshi 2 posts = 1 event).
# Deepseek off: unpinned answers prose (12/327 live failures, 2/14 bench to DeepInfra).
JUDGE_MODEL = _get("JUDGE_MODEL", "google/gemini-2.5-flash")

# Timeout: treat as new item and post. 25s normal, but 20 at once hit it; timeout =
# duplicate published. Headroom in 120s tick.
JUDGE_TIMEOUT_SECONDS = _get_int("JUDGE_TIMEOUT_SECONDS", 40)


# BRAIN / PERSONA: channel voice prepended to writer's prompt. Recent posts as voice
# examples (enough rhythm, minimal bloat).
PERSONA_RECENT_POSTS = _get_int("PERSONA_RECENT_POSTS", 15)


# STORIES: unit of work; items join, story posts when it moves.

# Story model: placement and gate (reading comprehension). Both fail open → duplicate
# story if timeout.
# Deepseek failed placement 7/week (4× spent 200-token thinking budget, returned
# nothing).
# Timeout raised 30→45 after measuring: 20 calls, slowest 22.2s. Placement timeout used
# to open duplicate story.
STORY_MODEL = _get("STORY_MODEL", "google/gemini-2.5-flash")
STORY_TIMEOUT_SECONDS = _get_int("STORY_TIMEOUT_SECONDS", 45)

# How many open stories shown to placement (index numbering error risk). Raised with
# STORY_IDLE_HOURS.
# Must stay >= actual open stories or hidden ones open duplicates (Apple news published
# twice).
STORY_MAX_OPEN = _get_int("STORY_MAX_OPEN", 30)

# How many unposted items shown to gate/writer from one story (keeps prompts bounded;
# all marked covered on post).
STORY_MAX_PENDING = _get_int("STORY_MAX_PENDING", 12)

# Story with no activity this long closes (new item cannot reopen). Measured: 12h split
# war into 8 stories in 6-day replay;
# 36h too short (Apple $5T cap: closed, returned 3 days later as new). 5 days = reader
# memory.
STORY_IDLE_HOURS = _get_int("STORY_IDLE_HOURS", 120)

# Hard end: stops broad situations staying live indefinitely (absorbing 1 item/11h).
STORY_MAX_HOURS = _get_int("STORY_MAX_HOURS", 168)

# Anti-double-post floor (was 25m, silenced Iran retaliation 2026-09-01). Gate now
# judges based on time elapsed.
STORY_MIN_GAP_MINUTES = _get_int("STORY_MIN_GAP_MINUTES", 6)

# Runaway stop (not editorial rule; gate weighs it). At 6 was a rule, silenced war's
# second half.
STORY_MAX_POSTS = _get_int("STORY_MAX_POSTS", 12)

# ROUNDUP: when items waiting >= ITEMS and >= MINUTES passed, post together (arithmetic,
# not editor).
STORY_DIGEST_ITEMS = _get_int("STORY_DIGEST_ITEMS", 3)
STORY_DIGEST_MINUTES = _get_int("STORY_DIGEST_MINUTES", 180)

# Breaks DEADLOCK: material while editor says no. Past MAX_QUIET_HOURS, story stopped,
# don't publish.
# 30-year Treasury out twice 2026-09-29 in 7h: 3 items over 37h silence + rule fired.
STORY_DIGEST_MAX_QUIET_HOURS = _get_int("STORY_DIGEST_MAX_QUIET_HOURS", 12)


# =============================================================================
# MISC
# =============================================================================

LOG_LEVEL = _get("LOG_LEVEL", "INFO")
MAX_BODY_CHARS = _get_int("MAX_BODY_CHARS", 5000)


def check(require_telegram: bool = False, require_openrouter: bool = False) -> list[str]:
    """Return configuration problems (empty = all good)."""
    problems: list[str] = []

    if require_telegram:
        if not TELEGRAM_BOT_TOKEN:
            problems.append("TELEGRAM_BOT_TOKEN is missing from .env")
        if not CHANNEL_ID:
            problems.append("CHANNEL_ID is missing from .env — nowhere to post")

    if require_openrouter and not OPENROUTER_API_KEY:
        problems.append("OPENROUTER_API_KEY is missing from .env")

    names = [s["name"] for s in SOURCES]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        problems.append(f"Duplicate source names in SOURCES: {sorted(duplicates)}")

    for source in SOURCES:
        if source["topic"] not in VALID_TOPICS:
            problems.append(f"Source '{source['name']}' has unknown topic "
                            f"'{source['topic']}' (expected {VALID_TOPICS})")
    for handle, topic in X_ACCOUNTS.items():
        if topic not in VALID_TOPICS:
            problems.append(f"X account '{handle}' has unknown topic "
                            f"'{topic}' (expected {VALID_TOPICS})")

    if not 1 <= MIN_IMPORTANCE <= 5:
        problems.append(f"MIN_IMPORTANCE must be between 1 and 5, not {MIN_IMPORTANCE}")

    return problems

# READING LINKED ARTICLES: 59% arrive with <120 chars body (reason posts restate first
# line). See nodes/article.py.

# Plain request then extraction (generous for slow sites, short enough not to stall).
ARTICLE_TIMEOUT_SECONDS = _get_int("ARTICLE_TIMEOUT_SECONDS", 15)

# Browser attempt (launch included); only for sites refusing plain request; mustn't hang
# round.
ARTICLE_BROWSER_TIMEOUT_SECONDS = _get_int("ARTICLE_BROWSER_TIMEOUT_SECONDS", 60)

# What's kept (writer sees full source; long-read would crowd wire items).
ARTICLE_MAX_CHARS = _get_int("ARTICLE_MAX_CHARS", 6000)

# THE LAST CHECK BEFORE SENDING (see nodes/echo.py). Shortlist wide (no cutoff between
# repeat and step); judge decides.
ECHO_SHORTLIST = _get_float("ECHO_SHORTLIST", 0.72)

# Reader memory window. Measured 2026-09-29 on 8 channel posts: deepseek 7/8 prose
# (fails open), mistral 8/8 schema+verdict,
# gemini schema ok but 30-year Treasury repeat through. Don't move without re-running
# this set.
ECHO_MODEL = _get("ECHO_MODEL", "mistralai/mistral-medium-3.1")
ECHO_WINDOW_HOURS = _get_int("ECHO_WINDOW_HOURS", 120)
ECHO_MAX_COMPARED = _get_int("ECHO_MAX_COMPARED", 40)
