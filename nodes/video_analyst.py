"""Decides whether a video or GIF goes out with a post. AI news channel only.

Each clip is downloaded, its length read with ffprobe, and anything over
MAX_VIDEO_SECONDS or MAX_VIDEO_MB is refused before a model sees it. The rest
go to Gemini with channels/<name>/video_rubric.md. The first one accepted wins.
Any failure means no video.
"""

from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

import config
from nodes.image_analyst import Choice
from utils import db, logger as log_setup, openrouter

log = log_setup.get("video_analyst")

_MAX_JUDGED = 3

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["accept", "reject"]},
        "reason": {"type": "string", "description": "One short sentence."},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}


async def _download(video: dict) -> tuple[Path, int] | None:
    """Save the clip to a temporary file. None if it fails or passes MAX_VIDEO_MB."""
    url = video["url"]
    if video.get("kind") == "embed":
        from utils import embeds
        path = await asyncio.to_thread(embeds.download, url, config.MAX_VIDEO_MB)
        return (path, path.stat().st_size) if path else None
    limit = config.MAX_VIDEO_MB * 1_000_000
    handle, name = tempfile.mkstemp(suffix=Path(url.split("?")[0]).suffix or ".mp4")
    path, size = Path(name), 0
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise ValueError(f"HTTP {response.status_code}")
                with os.fdopen(handle, "wb") as out:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > limit:
                            raise ValueError(f"over {config.MAX_VIDEO_MB} MB")
                        out.write(chunk)
        return path, size
    except Exception as error:  # noqa: BLE001
        log.info("Video not usable (%s): %s", error, url[:80])
        path.unlink(missing_ok=True)
        return None


def _duration(path: Path) -> float | None:
    """The clip's length in seconds, read by ffprobe. None if it cannot tell."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=20)
        return float(result.stdout.strip())
    except (ValueError, subprocess.SubprocessError, OSError):
        return None


def _mime(path: Path) -> str:
    return {".webm": "video/webm", ".mov": "video/quicktime"}.get(path.suffix.lower(), "video/mp4")


async def _judge(post_text: str, path: Path, kind: str) -> dict:
    """Ask Gemini whether this clip shows what the post says."""
    data = base64.b64encode(path.read_bytes()).decode()
    what = "a short looping GIF" if kind == "gif" else "a video"
    content = [
        {"type": "text", "text": f"Today is {datetime.now(timezone.utc):%d %B %Y}.\n\n"
                                 f"THE POST:\n{post_text}\n\nThe candidate is {what}:"},
        {"type": "video_url", "video_url": {"url": f"data:{_mime(path)};base64,{data}"}},
    ]
    return await asyncio.wait_for(
        openrouter.chat_json(
            model=config.VIDEO_MODEL, system=config.VIDEO_RUBRIC_PATH.read_text(),
            user=content, schema=SCHEMA, schema_name="video_choice",
            temperature=0.0, max_tokens=400),
        timeout=config.MEDIA_TIMEOUT_SECONDS,
    )


async def _judge_one(post_text: str, video: dict) -> tuple[str, str, bool]:
    """(verdict, reason, failed) for one clip, with its file always cleaned up."""
    saved = await _download(video)
    if saved is None:
        return "reject", "could not be downloaded, or too large to send", False
    path, _ = saved
    try:
        seconds = await asyncio.to_thread(_duration, path)
        if seconds is None:
            return "reject", "length could not be read", False
        if seconds > config.MAX_VIDEO_SECONDS:
            return "reject", f"{seconds:.0f}s, over the {config.MAX_VIDEO_SECONDS}s limit", False
        try:
            answer = await _judge(post_text, path, video.get("kind", "video"))
        except Exception as error:  # noqa: BLE001 - fail closed
            db.bump_counter("media_error")
            log.warning("Video check failed (%s) — sending without it", error)
            return "reject", f"check failed: {error}"[:200], True
        verdict = answer.get("verdict")
        if verdict not in ("accept", "reject"):
            return "reject", f"unexpected verdict {verdict!r}", True
        return verdict, str(answer.get("reason", ""))[:150], False
    finally:
        path.unlink(missing_ok=True)


async def choose(post_text: str, videos: list[dict]) -> Choice:
    """The first clip that shows what the post says, or an empty Choice."""
    notes, broke = [], False
    for video in videos[:_MAX_JUDGED]:
        verdict, reason, failed = await _judge_one(post_text, video)
        broke = broke or failed
        notes.append(f"{verdict} — {reason}")
        if verdict == "accept":
            log.info("Video chosen: %s", reason[:100])
            db.bump_counter("media_video_chosen")
            return Choice(url=video["url"], kind=video.get("kind") or "video",
                          reason="; ".join(notes))
    if videos:
        log.info("No video fits the post: %s", "; ".join(notes)[:160])
    return Choice(reason="; ".join(notes) or "no videos", failed=broke)
