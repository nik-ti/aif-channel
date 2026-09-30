"""Read a channel's PIPELINE list from profile.py as text, not by importing (avoids
module-level code needing API keys).
"""

from __future__ import annotations

import re

import paths

# Default fallback if profile.py parsing fails; never crash the dashboard over this.
DEFAULT_PIPELINE = [
    "dedup", "sorter", "fetch_article", "story_organizer",
    "gatekeeper", "writer", "editor", "publish",
]


def channel_pipeline(channel: str) -> list[str]:
    """The station names in channels/<channel>/profile.py's PIPELINE, in
    order, as literal strings — not the STAGES functions they route to."""
    text: str | None
    try:
        text = (paths.channel_dir(channel) / "profile.py").read_text(encoding="utf-8")
    except OSError:
        text = None
    if not text:
        return list(DEFAULT_PIPELINE)

    match = re.search(r'^PIPELINE\s*=\s*\[(.*?)\]', text, re.DOTALL | re.MULTILINE)
    if not match:
        return list(DEFAULT_PIPELINE)

    stations = re.findall(r'["\']([^"\']+)["\']', match.group(1))
    return stations or list(DEFAULT_PIPELINE)
