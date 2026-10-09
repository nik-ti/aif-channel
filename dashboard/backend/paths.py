"""Where the dashboard finds the channel: the project root (the folder holding config.py
and schema.sql), its database, its prompts and its .env. Found by looking for those
markers rather than counting parent folders, so moving the dashboard cannot break it."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values


def project_root() -> Path:
    """The channel project's root: the directory holding config.py and schema.sql."""
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "config.py").is_file() and (candidate / "schema.sql").is_file():
            return candidate
    raise RuntimeError("Could not find the project root from " + str(Path(__file__)))


ROOT_DIR = project_root()
ENV_PATH = ROOT_DIR / ".env"
PROMPTS_DIR = ROOT_DIR / "prompts"

# The stations in the order pipeline/graph.py runs them (a test checks they match).
STATIONS = [
    "dedup", "fetch_article", "labeler", "sorter", "company_limit",
    "writer", "editor", "repeat_check", "image_analyst", "video_analyst", "publish",
]


def env() -> dict[str, str | None]:
    """The project's .env, read fresh each time so an edit needs no restart."""
    return dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}


def database_path() -> Path:
    """The channel's database (same file config.py names)."""
    return ROOT_DIR / "data" / "aif-channel.db"


def database_ready() -> bool:
    return database_path().exists()


def channel_username() -> str:
    """The channel's Telegram @name without the @, or "" when it is a numeric id.
    Only an @name can be turned into a t.me link a non-member can open."""
    value = (env().get("CHANNEL_ID") or os.environ.get("CHANNEL_ID") or "").strip()
    return value[1:] if value.startswith("@") else ""
