"""GET /api/v1/nodes lists each LLM node in the pipeline with its model and system prompt.
The endpoint reads nodes/.py, config.py, and .env as text with regexes, not by importing (importing would run module-level code needing API keys).
It reads .env to show what model is actually running: config.py constants are defaults, and .env overrides them at runtime, just like MAX_POSTS_PER_HOUR today.
Accepts optional ?channel= to show that channel's PIPELINE and rubric from channels/<name>/profile.py and rubric.md.
"""

from __future__ import annotations

import os
import re
import traceback
from pathlib import Path

from dotenv import dotenv_values
from fastapi import APIRouter, Query

import paths
import pipeline
from channel_resolver import resolve_channel

router = APIRouter()

ROOT_DIR = paths.ROOT_DIR
NODES_DIR = ROOT_DIR / "nodes"
CONFIG_PATH = ROOT_DIR / "config.py"
ENV_PATH = paths.ENV_PATH

# Map PIPELINE station to LLM node id. Stations with no entry (fetch_article, publish,
# channel-added) have no model/prompt and are omitted.
STATION_TO_NODE: dict[str, str] = {
    "dedup": "dedup_judge",
    "sorter": "sorter",
    "story_organizer": "story_organizer",
    "gatekeeper": "gatekeeper",
    "writer": "writer",
    "editor": "editor",
    "repeat_check": "repeat_check",
    "image_analyst": "image_analyst",
    "video_analyst": "video_analyst",
}

# Mapping node to its (source file, prompt constant). Judge's SYSTEM_THREE_WAY is the
# one used by dedup.py check 5; SYSTEM is legacy (tools/check_dedup.py only).
PROMPT_SOURCES: dict[str, tuple[str, str]] = {
    "dedup_judge": ("judge.py", "SYSTEM_THREE_WAY"),
    "story_organizer": ("stories.py", "PLACE_SYSTEM"),
    "gatekeeper": ("stories.py", "GATE_SYSTEM"),
    "writer": ("writer.py", "PROMPT"),
    "editor": ("editor.py", "PROMPT"),
    "repeat_check": ("echo.py", "SYSTEM"),
}

# Map node to its config.py model variable.
MODEL_VARS: dict[str, str] = {
    "dedup_judge": "JUDGE_MODEL",
    "sorter": "SORTER_MODEL",
    "story_organizer": "STORY_MODEL",
    "gatekeeper": "STORY_MODEL",
    "writer": "WRITER_MODEL",
    "editor": "EDITOR_MODEL",
    "repeat_check": "ECHO_MODEL",
    "image_analyst": "IMAGE_MODEL",
    "video_analyst": "VIDEO_MODEL",
    "embeddings": "EMBEDDING_MODEL",
}

# node_name -> config.py variable name for its fallback model, where one exists.
FALLBACK_MODEL_VARS: dict[str, str] = {
    "editor": "EDITOR_FALLBACK_MODEL",
}

LABELS: dict[str, str] = {
    "dedup_judge": "Dedup judge",
    "sorter": "Sorter",
    "story_organizer": "Story organizer",
    "gatekeeper": "Gatekeeper",
    "writer": "Writer",
    "editor": "Editor",
    "repeat_check": "Repeat check",
    "image_analyst": "Image analyst",
    "video_analyst": "Video analyst",
    "embeddings": "Embeddings",
}

DESCRIPTIONS: dict[str, str] = {
    "dedup_judge": "Rules on two look-alike stories — same event, a continuation, or "
             "different — the deciding step behind duplicate check 5.",
    "sorter": "Scores every incoming item 1-5 for market impact and picks its "
              "topic — the only node that decides if something is worth "
              "covering at all.",
    "story_organizer": "Decides which running story a new item joins, or starts a "
                   "new one. Related closed threads remain available for 60 days "
                   "and can reopen without losing published history.",
    "gatekeeper": "Decides whether a story has moved enough since its last post to "
            "publish again.",
    "writer": "Rewrites the story into the channel's one house style.",
    "editor": "Reads the finished post against its source and approves or "
              "rejects it before it can be published.",
    "repeat_check": "The last station. Compares the finished post against every "
                    "visible post of the last 60 days, without a newest-post cap. "
                    "Cached embeddings retrieve all related posts; the judge reads "
                    "their combined information. Unavailable checks defer sending.",
    "image_analyst": "Looks at every candidate picture and picks the one that shows "
                     "what the post says, or none.",
    "video_analyst": "Watches candidate clips and keeps the first one that shows what "
                     "the post says. Over 2 minutes is refused before it is watched.",
    "embeddings": "Turns text into meaning-vectors so near-duplicate stories "
                  "can be shortlisted before the judge rules on them "
                  "(dedup check 4). No prompt — it is not an LLM call.",
}

# Fallback display order, used only if a profile's PIPELINE can't be parsed.
NODE_ORDER = ["dedup_judge", "sorter", "story_organizer", "gatekeeper",
              "writer", "editor", "repeat_check", "embeddings"]


def _node_order_for(channel: str) -> list[str]:
    """This channel's PIPELINE, translated into the LLM node ids above, in
    the order items actually flow through them. Embeddings isn't a PIPELINE
    station — it's the sub-step check 4 of dedup runs before the judge ever
    sees a pair — so it's appended whenever dedup (-> judge) is present,
    same placement the dashboard has always shown it at."""
    stations = pipeline.channel_pipeline(channel)
    order: list[str] = []
    for station in stations:
        node_id = STATION_TO_NODE.get(station)
        if node_id and node_id not in order:
            order.append(node_id)
    if not order:
        return list(NODE_ORDER)
    if "dedup_judge" in order:
        order.append("embeddings")
    return order


# Where a node does a different job on a channel, its own description wins.
CHANNEL_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "ai_news": {
        "sorter": "Scores every incoming item 1-5 for how useful it is to a regular "
                  "person today, names its kind and who can use it — the only node "
                  "that decides if something is worth covering at all.",
        "writer": "Writes the post in AI Flow's voice: simple, bold first line, "
                  "• lines, bold key words, link last, no emoji. Shown with the "
                  "voice file (persona.md) it is given in front of the prompt.",
        "editor": "Reads the finished post against its source and approves or rejects "
                  "it, including for JARGON. On a rewrite it is shown its own earlier reason.",
        "story_organizer": "Decides which running story a new item joins. On this "
                           "channel one product is one story.",
    },
}


def _channel_file(channel: str, name: str) -> str | None:
    """A prompt file that lives beside the channel's profile, or None."""
    try:
        return (paths.channel_dir(channel) / name).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _profile_string(channel: str, const_name: str) -> str | None:
    """A triple-quoted string constant from the channel's profile.py, read as text."""
    try:
        text = (paths.channel_dir(channel) / "profile.py").read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(rf'^{re.escape(const_name)}\s*=\s*"""(.*?)"""', text, re.DOTALL | re.MULTILINE)
    return match.group(1).strip() if match else None


def _channel_prompt(channel: str, node_id: str) -> str | None:
    """The prompt this channel really uses for node_id, where it is the channel's own."""
    if node_id == "writer":
        own = _channel_file(channel, "writer.md")
        persona = _channel_file(channel, "persona.md")
        if own and persona:
            return f"{persona}\n\n--- (persona.md above, writer.md below) ---\n\n{own}"
        return own
    if node_id == "editor":
        return _channel_file(channel, "editor.md")
    if node_id in ("image_analyst", "video_analyst"):
        return _channel_file(channel, node_id.replace("_analyst", "_rubric") + ".md")
    return None


def _channel_rubric(channel: str) -> str | None:
    """`channel`'s rubric — see channels/<name>/rubric.md."""
    path = paths.channel_dir(channel) / "rubric.md"
    try:
        return path.read_text()
    except OSError:
        return None


def _extract_prompt(file_path: Path, const_name: str) -> str | None:
    """Pull a triple-quoted constant out of a node source file as plain text."""
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[nodes] could not read {file_path}: {exc}")
        traceback.print_exc()
        return None

    pattern = re.compile(
        rf'^{re.escape(const_name)}\s*=\s*"""(.*?)"""', re.DOTALL | re.MULTILINE
    )
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1).strip()


def _extract_default_model(config_text: str, var_name: str) -> str | None:
    """Pull the DEFAULT out of `VAR = _get("VAR", "default/value")` in config.py.

    Also reads `VAR = _get("VAR", getattr(_profile, "VAR", "default/value"))`.
    """
    pattern = re.compile(
        rf'^{re.escape(var_name)}\s*=\s*_get\(\s*"{re.escape(var_name)}"\s*,\s*'
        rf'(?:getattr\(\s*_profile\s*,\s*"{re.escape(var_name)}"\s*,\s*)?"([^"]*)"',
        re.MULTILINE,
    )
    match = pattern.search(config_text)
    return match.group(1) if match else None


def _profile_value(channel: str, const_name: str) -> str | None:
    """A one-line string constant from the channel's profile.py, read as text."""
    try:
        text = (paths.channel_dir(channel) / "profile.py").read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(rf'^{re.escape(const_name)}\s*=\s*"([^"\n]*)"', text, re.MULTILINE)
    return match.group(1) if match else None


def _resolve_model(var_name: str, config_text: str, env_overrides: dict[str, str | None],
                   channel: str = "") -> str:
    """The value the running channel actually uses for `var_name`.

    Mirrors config.py: the channel's own .env override (MARKETS_SORTER_MODEL), then the
    shared one, then the channel profile's constant, then config.py's default.
    """
    prefixed = f"{channel.upper()}_{var_name}" if channel else ""
    value = ((prefixed and (env_overrides.get(prefixed) or os.environ.get(prefixed)))
             or env_overrides.get(var_name) or os.environ.get(var_name)
             or (channel and _profile_value(channel, var_name)))
    default = _extract_default_model(config_text, var_name)
    resolved = value if value else default
    return (resolved or "(unknown — not found in config.py)").strip()


@router.get("/nodes")
def get_nodes(channel: str | None = Query(default=None, description="Which channel's pipeline/rubric to read")):
    name = resolve_channel(channel)

    try:
        config_text = CONFIG_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[nodes] could not read {CONFIG_PATH}: {exc}")
        traceback.print_exc()
        config_text = ""

    env_overrides: dict[str, str | None] = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}

    nodes = []
    for node_id in _node_order_for(name):
        prompt: str | None = _channel_prompt(name, node_id)
        if prompt is None and node_id in PROMPT_SOURCES:
            filename, const_name = PROMPT_SOURCES[node_id]
            prompt = _extract_prompt(NODES_DIR / filename, const_name)
            notes = _profile_string(name, "STORY_PLACE_NOTES") if node_id == "story_organizer" else None
            if prompt and notes:
                prompt = f"{prompt}\n\n--- added for this channel (profile.py) ---\n\n{notes}"
        elif node_id == "sorter":
            # The sorter's rubric is the one prompt that belongs to the channel
            # rather than to the machinery, so it lives beside its profile.
            prompt = _channel_rubric(name)

        model = _resolve_model(MODEL_VARS[node_id], config_text, env_overrides, name)

        fallback_model: str | None = None
        if node_id in FALLBACK_MODEL_VARS:
            fallback_model = _resolve_model(FALLBACK_MODEL_VARS[node_id], config_text, env_overrides, name)
            if not fallback_model or fallback_model.startswith("(unknown"):
                fallback_model = None

        nodes.append(
            {
                "id": node_id,
                "label": LABELS.get(node_id, node_id.replace("_", " ").title()),
                "description": CHANNEL_DESCRIPTIONS.get(name, {}).get(node_id)
                               or DESCRIPTIONS.get(node_id, ""),
                "model": model,
                "fallback_model": fallback_model,
                "prompt": prompt,
            }
        )

    return {"channel": name, "ready": paths.database_ready(name), "nodes": nodes}
