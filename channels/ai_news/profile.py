"""Configuration that makes this the AI news channel: AI tools and releases that regular
people can use, written simply. Shared machinery (nodes/, brain/, utils/) knows none of this.
Beside this file: rubric.md (what is worth posting), persona.md (voice), writer.md and
editor.md (this channel's own writer and editor prompts), and the media rubrics."""

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
WRITER_PROMPT_PATH = HERE / "writer.md"
EDITOR_PROMPT_PATH = HERE / "editor.md"

# Both analysts, and article pages are searched for pictures and clips too.
IMAGE_RUBRIC_PATH = HERE / "image_rubric.md"
VIDEO_RUBRIC_PATH = HERE / "video_rubric.md"
CHECK_VIDEOS = True
COLLECT_ARTICLE_MEDIA = True

MIN_IMPORTANCE = 4

# MUST match rubric.md: the provider enforces these lists.
TOPICS = ("launch", "tool", "resource", "other")
VALID_TOPICS = ("launch", "tool", "resource")

# The sorter's third question here is "who can use this today?". "none" caps the
# score at 3, exactly like "no market reprices" on Market One.
SORTER_AXIS = "who_can_use"
MARKETS = ("everyone", "creators", "business", "students", "developers", "none")

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

# None yet. A channel with no accounts never touches the shared tweet stream,
# and it has its own reader group so it could never take Market One's tweets.
X_ACCOUNTS: dict[str, str] = {}
NO_MEDIA_SOURCES: set[str] = set()
TWEET_STREAM_GROUP = "news-channel-ai_news"

# AI/TLDR dates its items at midnight, so a day-old cutoff drops most of them.
ARTICLE_MAX_AGE_HOURS = 48

# OpenAI's pages sit behind a JavaScript challenge that even the stealth browser
# cannot pass; this free reader service can. Only used when both fail.
READER_FALLBACK_URL = "https://r.jina.ai/"

# The editor sees its own earlier rejection on a rewrite.
EDITOR_REMEMBERS_REWRITES = True

# The placer's examples are about markets. On this channel a story is one product.
STORY_PLACE_NOTES = """ON THIS CHANNEL A STORY IS ONE PRODUCT OR ONE RELEASE. The examples above are
from a markets channel; here the rule is simpler. Two items belong together only
when they are about the SAME product, model or tool: its launch, its rollout to
more users, a guide to it, a price change for it.

  - "Introducing dots" and "Dots rolls out to Plus users"           -> ONE story.
  - "Introducing dots" and "Introducing GPT-6.1 Sol"               -> TWO stories.
  - "Claude Code adds mods" and "Claude gets a new Opus model"     -> TWO stories.

Being from the same COMPANY is not enough. Being announced at the same EVENT is
not enough."""

# "DevDay 2026" was dropped as "a hypothetical future event" without this.
SORTER_SHOWS_DATE = True

# The economic calendar is a markets thing.
USE_ECONOMIC_CALENDAR = False

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

# Every post is signed. The text lives in .env as AI_NEWS_SIGNATURE_HTML, e.g.
# <a href="https://t.me/yourchannel">Channel Name | Subscribe</a>
REQUIRES_SIGNATURE = True

WRONG_TOPIC_RULE = ("not about AI tools, AI products or AI models that people can use")
EXTRA_EDITOR_RULES = {
    "JARGON": "uses a technical word a 12-year-old would not know, without explaining it",
}
EXTRA_FIXABLE_RULES = ("JARGON",)

# The markets stations, plus the video analyst.
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
    "video_analyst",
    "publish",
]
