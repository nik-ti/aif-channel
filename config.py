# Every setting for AI Flow (@ai_flow_daily). Secrets live in .env; everything else
# has a default here that a line in .env can override (same name).
# The prompts are text files in prompts/; this file only points at them.

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "schema.sql"
PROMPTS = HERE / "prompts"

_ENV = dotenv_values(HERE / ".env")


def _get(name: str, default: str = "") -> str:
    """Read a setting from .env (or the environment), else the default."""
    value = _ENV.get(name) or os.environ.get(name)
    return (value if value is not None else default).strip()


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


CHANNEL_NAME = "AI Flow"
DB_PATH = HERE / "data" / "aif-channel.db"
LOG_PATH = HERE / "logs" / "aif-channel.log"


# SECRETS (from .env)

TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = _get("CHANNEL_ID")          # "@name" or "-100..."
ERROR_CHAT_ID = _get("ERROR_CHAT_ID")    # your DM, for error alerts
OPENROUTER_API_KEY = _get("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = _get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# Every post is signed, e.g. <a href="https://t.me/ai_flow_daily">AI Flow | Subscribe</a>
SIGNATURE_HTML = _get("SIGNATURE_HTML")


# PROMPTS

RUBRIC_PATH = PROMPTS / "rubric.md"          # what is worth posting (the sorter)
PERSONA_PATH = PROMPTS / "persona.md"        # the voice, in front of the writer's prompt
WRITER_PROMPT_PATH = PROMPTS / "writer.md"
EDITOR_PROMPT_PATH = PROMPTS / "editor.md"
IMAGE_RUBRIC_PATH = PROMPTS / "image_rubric.md"
VIDEO_RUBRIC_PATH = PROMPTS / "video_rubric.md"


# WHAT GETS PUBLISHED

# The sorter scores 1-5; only items at or above this are posted.
MIN_IMPORTANCE = _get_int("MIN_IMPORTANCE", 4)

# MUST match rubric.md: the provider enforces these lists.
TOPICS = ("launch", "tool", "skill", "resource", "other")
VALID_TOPICS = ("launch", "tool", "skill", "resource")

# The sorter's third question, "who can use this today?". "none" caps the score at 3.
# Stored in the items.market column.
SORTER_AXIS = "who_can_use"
SORTER_AXIS_VALUES = ("everyone", "creators", "business", "students", "developers", "none")

# Guides and skill packs: useful, but a channel full of them reads like a list
# (six skills.sh posts went out in 16 minutes on 2026-10-05). At most 2 of each a
# day, at least 3 hours apart: {topic: (max posts in 24 hours, min hours between)}.
TOPIC_LIMITS = {"resource": (2, 3), "skill": (2, 3)}

# How long an item held back by TOPIC_LIMITS waits for a free slot (nodes/reserve.py).
RESERVE_DAYS = _get_int("RESERVE_DAYS", 3)

# Feeds like Future Tools give only "Source: x | Release date: y", so the article is
# read before the sorter judges it.
SORTER_READS_ARTICLE = True

# "DevDay 2026" was dropped as "a hypothetical future event" without this.
SORTER_SHOWS_DATE = True


# SOURCES

SOURCES = [
    # Lab announcements. Anthropic has no feed of its own; this one is rebuilt
    # from its news page by a community project on GitHub.
    {"name": "openai",     "topic": "launch", "url": "https://openai.com/news/rss.xml"},
    {"name": "anthropic",  "topic": "launch",
     "url": "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml"},
    {"name": "hf_blog",    "topic": "launch", "url": "https://huggingface.co/blog/feed.xml"},

    # New tools and releases, already sorted by someone.
    {"name": "ai_tldr",    "topic": "tool",   "url": "https://ai-tldr.dev/feed.xml"},
    # 33 MB in full; the newest entries are all in the first megabyte.
    {"name": "tom_doerr",  "topic": "tool",
     "url": "https://tom-doerr.github.io/repo_posts/feed.xml", "max_bytes": 1_000_000},

    # Future Tools (Matt Wolfe's AI news list). Links go to the original article and
    # each item states its release date. 1000 items; the newest are at the top.
    {"name": "futuretools", "topic": "launch",
     "url": "https://www.futuretools.io/news/rss.xml", "max_bytes": 150_000},

    # MindStudio removed 2026-10-04: its explainers of releases from days earlier
    # were posted as "just launched".

    # Pages with no feed, watched by nodes/fetch_pages.py: plain request first,
    # stealth browser if that fails. A link matching link_pattern that was not
    # there last time is a new story.
    {"name": "xai", "kind": "page", "topic": "launch", "every_minutes": 60,
     "url": "https://x.ai/news", "link_pattern": r"^https://x\.ai/news/[a-z0-9-]+$"},
    # Skills climbing the chart, and companies newly publishing official skills.
    {"name": "skills_trending", "kind": "page", "topic": "tool", "every_minutes": 360,
     "url": "https://www.skills.sh/trending",
     "link_pattern": r"^https://www\.skills\.sh/[a-z0-9][\w.-]*/[\w.-]+/[\w.-]+$"},
    {"name": "skills_official", "kind": "page", "topic": "tool", "every_minutes": 720,
     "url": "https://skills.sh/official",
     "link_pattern": r"^https://skills\.sh/(?!(packs|topic|official|audits|docs|agent)$)[a-z0-9-]+$"},
]

# X accounts read from the shared tweet relay (/home/nikita/trading/infra/tweet-relay).
# None yet. Adding one also needs the relay's accounts.txt and a relay restart.
X_ACCOUNTS: dict[str, str] = {}
NO_MEDIA_SOURCES: set[str] = set()

# AI/TLDR dates its items at midnight, so a day-old cutoff drops most of them.
ARTICLE_MAX_AGE_HOURS = _get_int("ARTICLE_MAX_AGE_HOURS", 48)

# OpenAI's pages sit behind a JavaScript challenge that even the stealth browser
# cannot pass; this free reader service can. Only used when both fail.
READER_FALLBACK_URL = "https://r.jina.ai/"

# Article pages are searched for pictures and clips too, and clips are watched.
COLLECT_ARTICLE_MEDIA = True
CHECK_VIDEOS = True


# HOW POSTS LOOK

# No emoji at all (nikita, 2026-10-04): emphasis comes from bold words and line
# breaks. The bullet is the one symbol a post may use.
POST_MARKS: dict[str, str] = {}
BULLET = "•"
ALLOW_FLAG_MARKS = False

# The writer ends the post with <a href="LINK">Try it here</a>; the publisher fills
# in the thing itself. AI/TLDR pages list the official link first.
LINK_TO_PRODUCT = True
PRODUCT_LINK_PAGES = ("ai-tldr.dev",)
LINK_FALLBACK_TEXT = "Link"

# One person writes this channel: no two posts open the same way.
VARY_WRITING = True

# Short sources (X posts) become BRIEF posts to avoid invention.
BRIEF_SOURCE_CHARS = _get_int("BRIEF_SOURCE_CHARS", 400)


# THE EDITOR'S CHANNEL RULES

WRONG_TOPIC_RULE = "not about AI tools, AI products or AI models that people can use"
EXTRA_EDITOR_RULES = {
    "JARGON": "uses a technical word a 12-year-old would not know, without explaining it",
}
EXTRA_FIXABLE_RULES = frozenset({"JARGON"})

# On a rewrite the editor sees its own earlier rejection, so it cannot reverse
# itself ("say units of text" → "say tokens").
EDITOR_REMEMBERS_REWRITES = True

# The placer's built-in examples are about markets. On this channel a story is one product.
STORY_PLACE_NOTES = """ON THIS CHANNEL A STORY IS ONE PRODUCT OR ONE RELEASE. The examples above are
from a markets channel; here the rule is simpler. Two items belong together only
when they are about the SAME product, model or tool: its launch, its rollout to
more users, a guide to it, a price change for it.

  - "Introducing dots" and "Dots rolls out to Plus users"           -> ONE story.
  - "Introducing dots" and "Introducing GPT-6.1 Sol"               -> TWO stories.
  - "Claude Code adds mods" and "Claude gets a new Opus model"     -> TWO stories.

Being from the same COMPANY is not enough. Being announced at the same EVENT is
not enough."""


# TIMING AND LIMITS

POLL_MINUTES = _get_int("POLL_MINUTES", 10)

# Tweet relay. TWEET_STREAM_GROUP must stay fixed (a new name skips or re-reads).
REDIS_URL = _get("REDIS_URL", "redis://localhost:6379/0")
TWEET_STREAM_KEY = _get("TWEET_STREAM_KEY", "tweets:stream")
TWEET_STREAM_GROUP = _get("TWEET_STREAM_GROUP", "news-channel-ai_news")
X_MAX_AGE_MINUTES = _get_int("X_MAX_AGE_MINUTES", 45)  # Stop restart floods.
X_MAX_BURST = _get_int("X_MAX_BURST", 25)

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
# different 0.785-0.900 (overlap), so it only shortlists; check 5 decides.
COSINE_SHORTLIST = _get_float("COSINE_SHORTLIST", 0.72)
COSINE_CERTAIN = _get_float("COSINE_CERTAIN", 0.95)  # Near-verbatim; merge without check 5.
COSINE_WINDOW_HOURS = _get_int("COSINE_WINDOW_HOURS", 48)
DEDUP_TOP_K = _get_int("DEDUP_TOP_K", 3)

# Duplicates in a sample landed within 10.1h; false merges were 24h apart (recurring reports).
DUPLICATE_MAX_GAP_HOURS = _get_int("DUPLICATE_MAX_GAP_HOURS", 12)

EMBEDDING_MODEL = _get("EMBEDDING_MODEL", "openai/text-embedding-3-small")


# AI MODELS (all through OpenRouter)

SORTER_MODEL = _get("SORTER_MODEL", "google/gemini-2.5-flash")
WRITER_MODEL = _get("WRITER_MODEL", "deepseek/deepseek-v3.2")

# The editor checks a post against its source and fails CLOSED. It must be a
# different lab from the writer. Don't move it without pairs containing known
# falsehoods. MiniMax failed 28 times in one week, so it is the fallback ("" = none).
EDITOR_MODEL = _get("EDITOR_MODEL", "mistralai/mistral-medium-3.1")
EDITOR_FALLBACK_MODEL = _get("EDITOR_FALLBACK_MODEL", "minimax/minimax-m2.7")
EDITOR_TIMEOUT_SECONDS = _get_int("EDITOR_TIMEOUT_SECONDS", 60)

# Alerts you if the editor starts rejecting an unusual share of posts.
EDITOR_DECLINE_ALERT_RATE = _get_float("EDITOR_DECLINE_ALERT_RATE", 0.5)
EDITOR_DECLINE_WINDOW = _get_int("EDITOR_DECLINE_WINDOW", 20)

# A post rejected for a FIXABLE rule goes back to the writer once with the reason.
MAX_REWRITES = _get_int("MAX_REWRITES", 1)

# Dedup check 5: same event, different, or a continuation. 39/40 on real pairs.
JUDGE_MODEL = _get("JUDGE_MODEL", "google/gemini-2.5-flash")
JUDGE_TIMEOUT_SECONDS = _get_int("JUDGE_TIMEOUT_SECONDS", 40)

# Recent posts shown to the writer.
PERSONA_RECENT_POSTS = _get_int("PERSONA_RECENT_POSTS", 15)


# STORIES: items join a story; a story posts when it has moved.

STORY_MODEL = _get("STORY_MODEL", "google/gemini-2.5-flash")
STORY_TIMEOUT_SECONDS = _get_int("STORY_TIMEOUT_SECONDS", 45)

# Must stay >= the real number of open stories, or hidden ones open duplicates.
STORY_MAX_OPEN = _get_int("STORY_MAX_OPEN", 30)
# Unposted items shown to the gate and writer from one story.
STORY_MAX_PENDING = _get_int("STORY_MAX_PENDING", 12)
STORY_IDLE_HOURS = _get_int("STORY_IDLE_HOURS", 120)
STORY_MAX_HOURS = _get_int("STORY_MAX_HOURS", 168)
# Floor against two wires seconds apart becoming two posts; the gate weighs the rest.
STORY_MIN_GAP_MINUTES = _get_int("STORY_MIN_GAP_MINUTES", 6)
STORY_MAX_POSTS = _get_int("STORY_MAX_POSTS", 12)  # runaway stop

# Roundup: when ITEMS have waited MINUTES, the gate is asked once whether together
# they say something new; past MAX_QUIET_HOURS the story is over.
STORY_DIGEST_ITEMS = _get_int("STORY_DIGEST_ITEMS", 3)
STORY_DIGEST_MINUTES = _get_int("STORY_DIGEST_MINUTES", 180)
STORY_DIGEST_MAX_QUIET_HOURS = _get_int("STORY_DIGEST_MAX_QUIET_HOURS", 12)


# READING LINKED ARTICLES (nodes/article.py)

ARTICLE_TIMEOUT_SECONDS = _get_int("ARTICLE_TIMEOUT_SECONDS", 15)
ARTICLE_BROWSER_TIMEOUT_SECONDS = _get_int("ARTICLE_BROWSER_TIMEOUT_SECONDS", 60)
ARTICLE_MAX_CHARS = _get_int("ARTICLE_MAX_CHARS", 6000)


# THE LAST CHECK BEFORE SENDING (nodes/echo.py): reader memory over 60 days.

ECHO_SHORTLIST = _get_float("ECHO_SHORTLIST", 0.60)
# 8/8 on schema and verdict on 2026-09-29; re-test on known repeats before moving it.
ECHO_MODEL = _get("ECHO_MODEL", "mistralai/mistral-medium-3.1")
MEMORY_RETENTION_DAYS = max(1, _get_int("MEMORY_RETENTION_DAYS", 60))
ECHO_WINDOW_HOURS = min(max(1, _get_int("ECHO_WINDOW_HOURS", 1440)), MEMORY_RETENTION_DAYS * 24)
ECHO_BATCH_CHARS = max(1000, _get_int("ECHO_BATCH_CHARS", 16000))
STORY_MEMORY_HOURS = min(max(1, _get_int("STORY_MEMORY_HOURS", 1440)), MEMORY_RETENTION_DAYS * 24)
STORY_MEMORY_SHORTLIST = _get_float("STORY_MEMORY_SHORTLIST", 0.60)


# THE MEDIA ANALYSTS. Measured 2026-10-01: about $0.0007 per image and $0.003 for a
# 6 MB video on Flash.

IMAGE_MODEL = _get("IMAGE_MODEL", "google/gemini-2.5-flash")
VIDEO_MODEL = _get("VIDEO_MODEL", "google/gemini-2.5-flash")
MEDIA_TIMEOUT_SECONDS = _get_int("MEDIA_TIMEOUT_SECONDS", 60)
MAX_IMAGES_JUDGED = _get_int("MAX_IMAGES_JUDGED", 6)
MAX_VIDEO_SECONDS = _get_int("MAX_VIDEO_SECONDS", 120)
# Telegram's limit for sending a file by its address; bigger could not go out anyway.
MAX_VIDEO_MB = _get_int("MAX_VIDEO_MB", 20)


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
        if not SIGNATURE_HTML:
            problems.append("SIGNATURE_HTML is missing from .env — every post is signed")

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
