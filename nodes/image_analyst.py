"""Chooses the one picture that goes out with a post, or none.

Every candidate is downloaded and shown to a vision model with the channel's
rubric (channels/<name>/image_rubric.md). The model judges each one and names
the best it accepted. "None of these" is a normal answer. Any failure means no
picture: an unchecked image never goes out.
"""

from __future__ import annotations

import asyncio
import base64
import io
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

import config
from utils import db, logger as log_setup, openrouter

log = log_setup.get("image_analyst")

_MAX_BYTES = 5_000_000
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0"

SCHEMA = {
    "type": "object",
    "properties": {
        "images": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "verdict": {"type": "string", "enum": ["accept", "reject"]},
                    "reason": {"type": "string", "description": "One short sentence."},
                },
                "required": ["index", "verdict", "reason"],
                "additionalProperties": False,
            },
        },
        "best": {"type": "integer", "description": "Index of the best accepted image, 0 for none."},
    },
    "required": ["images", "best"],
    "additionalProperties": False,
}


@dataclass
class Choice:
    url: str = ""
    kind: str = ""
    reason: str = ""
    failed: bool = False        # the check itself broke, as opposed to finding nothing


async def _fetch_image(url: str) -> bytes | None:
    """Download one image. None if it is missing, not an image, too big or too small."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                     headers={"User-Agent": _UA}) as client:
            response = await client.get(url)
        if response.status_code != 200 or len(response.content) > _MAX_BYTES:
            return None
        if not response.headers.get("content-type", "").startswith("image/"):
            return None
        from PIL import Image
        with Image.open(io.BytesIO(response.content)) as picture:
            if min(picture.size) < 200:
                return None
        return response.content
    except Exception as error:  # noqa: BLE001 - a missing picture is not a problem
        log.debug("Could not fetch image %s: %s", url[:80], error)
        return None


def _mime(data: bytes) -> str:
    if data[:8].startswith(b"\x89PNG"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


async def _judge(post_text: str, images: list[tuple[str, bytes]]) -> dict:
    """Ask the vision model to judge the numbered images against the rubric."""
    # Today's date, or a chart labelled with a recent month reads as "the future".
    today = datetime.now(timezone.utc).strftime("%d %B %Y")
    content: list[dict] = [{"type": "text", "text": f"Today is {today}.\n\nTHE POST:\n"
                            f"{post_text}\n\n{len(images)} candidate image(s) follow, "
                            f"numbered from 1."}]
    for number, (_, data) in enumerate(images, start=1):
        content.append({"type": "text", "text": f"Image {number}:"})
        content.append({"type": "image_url", "image_url": {
            "url": f"data:{_mime(data)};base64,{base64.b64encode(data).decode()}"}})
    return await asyncio.wait_for(
        openrouter.chat_json(
            model=config.IMAGE_MODEL, system=config.IMAGE_RUBRIC_PATH.read_text(),
            user=content, schema=SCHEMA, schema_name="image_choice",
            temperature=0.0, max_tokens=900),
        timeout=config.MEDIA_TIMEOUT_SECONDS,
    )


async def choose(post_text: str, urls: list[str]) -> Choice:
    """The best picture for this post, or an empty Choice if none should go out."""
    urls = list(dict.fromkeys(u for u in urls if u))
    if not urls:
        return Choice(reason="no images")

    fetched = await asyncio.gather(*(_fetch_image(u) for u in urls))
    images = [(u, data) for u, data in zip(urls, fetched) if data][:config.MAX_IMAGES_JUDGED]
    if not images:
        return Choice(reason="no image could be downloaded")

    try:
        answer = await _judge(post_text, images)
    except Exception as error:  # noqa: BLE001 - fail closed: no picture, the post still goes
        db.bump_counter("media_error")
        log.warning("Image check failed (%s) — sending without a picture", error)
        return Choice(reason=f"check failed: {error}"[:200], failed=True)

    verdicts = {}
    for row in answer.get("images") or []:
        index = row.get("index")
        if isinstance(index, int) and 1 <= index <= len(images):
            verdicts[index] = (row.get("verdict"), str(row.get("reason", ""))[:150])
    summary = "; ".join(f"{n}: {v} — {why}" for n, (v, why) in sorted(verdicts.items()))

    best = answer.get("best")
    if isinstance(best, int) and verdicts.get(best, ("",))[0] == "accept":
        url = images[best - 1][0]
        log.info("Image %d of %d chosen: %s", best, len(images), verdicts[best][1][:100])
        db.bump_counter("media_image_chosen")
        return Choice(url=url, kind="image", reason=summary)

    log.info("None of %d image(s) fits the post: %s", len(images), summary[:160])
    db.bump_counter("media_image_none")
    return Choice(reason=summary or "none accepted")
