"""GET /api/v1/nodes lists each LLM step of the pipeline with its model and prompt.

It reads prompts/, nodes/*.py, config.py and .env as text rather than importing them
(importing would run module-level code that needs API keys). .env is read because it
can override a model that config.py only gives a default for.
"""

from __future__ import annotations

import os
import re
import traceback
from pathlib import Path

from fastapi import APIRouter

import paths

router = APIRouter()

NODES_DIR = paths.ROOT_DIR / "nodes"
CONFIG_PATH = paths.ROOT_DIR / "config.py"

# Pipeline station -> the LLM step shown for it. fetch_article and publish use no model.
STATION_TO_NODE: dict[str, str] = {
    "dedup": "dedup_judge",
    "labeler": "labeler",
    "sorter": "sorter",
    "writer": "writer",
    "editor": "editor",
    "repeat_check": "repeat_check",
    "image_analyst": "image_analyst",
    "video_analyst": "video_analyst",
}

# Prompts that live in prompts/.
PROMPT_FILES: dict[str, str] = {
    "labeler": "labeler.md",
    "sorter": "rubric.md",
    "editor": "editor.md",
    "image_analyst": "image_rubric.md",
    "video_analyst": "video_rubric.md",
}

# Prompts that live in code, as (source file, constant). SYSTEM_THREE_WAY is the one
# dedup check 5 uses.
PROMPT_SOURCES: dict[str, tuple[str, str]] = {
    "dedup_judge": ("judge.py", "SYSTEM_THREE_WAY"),
    "repeat_check": ("echo.py", "SYSTEM"),
}

MODEL_VARS: dict[str, str] = {
    "dedup_judge": "JUDGE_MODEL",
    "labeler": "LABELER_MODEL",
    "sorter": "SORTER_MODEL",
    "writer": "WRITER_MODEL",
    "editor": "EDITOR_MODEL",
    "repeat_check": "ECHO_MODEL",
    "image_analyst": "IMAGE_MODEL",
    "video_analyst": "VIDEO_MODEL",
    "embeddings": "EMBEDDING_MODEL",
}

FALLBACK_MODEL_VARS: dict[str, str] = {"editor": "EDITOR_FALLBACK_MODEL"}

LABELS: dict[str, str] = {
    "dedup_judge": "Dedup judge",
    "labeler": "Labeler",
    "sorter": "Sorter",
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
    "labeler": "Picks the item's kind (new_product, new_model, feature, pricing, tool, "
               "skill, guide, roundup, other) and the company that made it, each from a "
               "fixed list; anything off the list is stored as 'other'. A cheap model. "
               "Checked with tools/check_labels.py.",
    "sorter": "Scores every incoming item 1-5 for how useful it is to a regular "
              "person today and names who can use it — the only node that decides "
              "if something is worth covering at all. It is given the labels.",
    "writer": "Writes the post in AI Flow's voice: simple, bold first line, "
              "• lines, bold key words, link last, no emoji. Shown with the "
              "voice file (persona.md) it is given in front of the prompt.",
    "editor": "Reads the finished post against its source and approves or rejects "
              "it, including for JARGON. On a rewrite it is shown its own earlier reason.",
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


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _triple_quoted(text: str, const_name: str) -> str | None:
    """A `NAME = \"\"\"...\"\"\"` constant out of Python source, as plain text."""
    match = re.search(rf'^{re.escape(const_name)}\s*=\s*"""(.*?)"""', text, re.DOTALL | re.MULTILINE)
    return match.group(1).strip() if match else None


def _prompt(node_id: str, config_text: str) -> str | None:
    """The prompt this step really sends."""
    if node_id == "writer":
        own = _read(paths.PROMPTS_DIR / "writer.md")
        persona = _read(paths.PROMPTS_DIR / "persona.md")
        if own and persona:
            return f"{persona}\n\n--- (persona.md above, writer.md below) ---\n\n{own}"
        return own
    if node_id in PROMPT_FILES:
        return _read(paths.PROMPTS_DIR / PROMPT_FILES[node_id])
    if node_id in PROMPT_SOURCES:
        filename, const_name = PROMPT_SOURCES[node_id]
        source = _read(NODES_DIR / filename)
        prompt = _triple_quoted(source, const_name) if source else None
        return prompt
    return None


def _resolve_model(var_name: str, config_text: str, env: dict[str, str | None]) -> str:
    """The model the channel actually runs: an override in .env, else config.py's default."""
    value = env.get(var_name) or os.environ.get(var_name)
    if not value:
        match = re.search(rf'^{re.escape(var_name)}\s*=\s*_get\(\s*"{re.escape(var_name)}"\s*,\s*"([^"]*)"',
                          config_text, re.MULTILINE)
        value = match.group(1) if match else None
    return (value or "(unknown — not found in config.py)").strip()


@router.get("/nodes")
def get_nodes():
    try:
        config_text = CONFIG_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[nodes] could not read {CONFIG_PATH}: {exc}")
        traceback.print_exc()
        config_text = ""
    env = paths.env()

    order = [STATION_TO_NODE[s] for s in paths.STATIONS if s in STATION_TO_NODE]
    # Embeddings is not a station: it is dedup's check 4, shown after the judge.
    order.append("embeddings")

    nodes = []
    for node_id in order:
        fallback = None
        if node_id in FALLBACK_MODEL_VARS:
            fallback = _resolve_model(FALLBACK_MODEL_VARS[node_id], config_text, env)
            if fallback.startswith("(unknown"):
                fallback = None
        nodes.append({
            "id": node_id,
            "label": LABELS.get(node_id, node_id.replace("_", " ").title()),
            "description": DESCRIPTIONS.get(node_id, ""),
            "model": _resolve_model(MODEL_VARS[node_id], config_text, env),
            "fallback_model": fallback,
            "prompt": _prompt(node_id, config_text),
        })

    return {"ready": paths.database_ready(), "nodes": nodes}
