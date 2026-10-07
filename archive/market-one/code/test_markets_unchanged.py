"""Proves Market One's prompts, schemas and marks are exactly what they were before
the AI channel was added, by comparing them with hashes saved on 2026-10-04.

Run: CHANNEL=markets /usr/bin/python3 tests/test_markets_unchanged.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

if config.CHANNEL != "markets":
    print("run with CHANNEL=markets")
    sys.exit(1)

from nodes import editor, sorter, stories, writer  # noqa: E402

current = {
    "writer_prompt": writer.PROMPT, "writer_emoji_rule": writer.EMOJI_RULE,
    "editor_prompt": editor.PROMPT,
    "editor_schema": json.dumps(editor.SCHEMA, sort_keys=True),
    "editor_rules": json.dumps(editor.RULES, sort_keys=True),
    "sorter_prompt": sorter.PROMPT,
    "sorter_schema": json.dumps(sorter.SCHEMA, sort_keys=True),
}
for name in dir(stories):
    value = getattr(stories, name)
    if name.isupper() and isinstance(value, str) and len(value) > 200:
        current["stories_" + name] = value

saved = json.loads((ROOT / "tests/fixtures/markets_prompts.sha256.json").read_text())
failed = [name for name, digest in saved.items()
          if hashlib.sha256(current.get(name, "").encode()).hexdigest() != digest]

# The marks and the bullet live in config; checked by value, they are short.
if config.BULLET != "▪️" or "📍" not in config.POST_MARKS or not config.ALLOW_FLAG_MARKS:
    failed.append("marks")
if config.TWEET_STREAM_GROUP != "news-channel" or config.ARTICLE_MAX_AGE_HOURS != 24:
    failed.append("collect settings")
if config.SIGNATURE_HTML or config.LINK_TO_PRODUCT:
    failed.append("publisher settings")

print(f"{len(saved) + 3 - len(failed)} passed, {len(failed)} failed")
for name in failed:
    print("  CHANGED", name)
sys.exit(1 if failed else 0)
