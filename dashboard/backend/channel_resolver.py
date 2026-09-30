"""Resolve a dashboard request's ?channel= parameter to a real channel and list channels for the switcher.
Fallback is fixed (markets), never .env, so the API matches spec "defaulting to markets"."""

from __future__ import annotations

import re

import paths

DEFAULT_CHANNEL = "markets"


def resolve_channel(requested: str | None) -> str:
    """The channel a request means. An unknown or missing name falls back to
    the default rather than erroring — a stale bookmark or an old shared
    link should degrade gracefully, not break."""
    names = paths.list_channel_names()
    if requested and requested in names:
        return requested
    if DEFAULT_CHANNEL in names:
        return DEFAULT_CHANNEL
    return names[0] if names else DEFAULT_CHANNEL


def _profile_text(channel: str) -> str | None:
    try:
        return (paths.channel_dir(channel) / "profile.py").read_text(encoding="utf-8")
    except OSError:
        return None


def _display_name(channel: str) -> str:
    """A human label. Prefers the channel's own NAME constant, falling back
    to a title-cased version of the directory name — never a made-up name."""
    text = _profile_text(channel)
    source = channel
    if text:
        match = re.search(r'^NAME\s*=\s*["\']([^"\']+)["\']', text, re.M)
        if match:
            source = match.group(1)
    words = [w for w in re.split(r"[_\-]+", source) if w]
    return " ".join(w.upper() if w.lower() == "ai" else w.capitalize() for w in words)


def list_channels() -> list[dict]:
    """Every channel plus whether it has a database yet — what the
    dashboard's switcher needs and nothing more."""
    return [
        {"id": name, "name": _display_name(name), "ready": paths.database_ready(name)}
        for name in paths.list_channel_names()
    ]
