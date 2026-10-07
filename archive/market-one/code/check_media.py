"""Run the image and video analysts on hand-labelled real media and score them.

The labels were set by hand on 2026-10-01 from the markets channel's own posts,
against the rubric in SPEC.md. Run this before changing a rubric or a model.
Costs about $0.05. Run: CHANNEL=markets /usr/bin/python3 tools/check_media.py --labelled
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from utils import persona_loader  # noqa: E402
from nodes import image_analyst, video_analyst  # noqa: E402
from utils import db  # noqa: E402

LINE = "─" * 74

# The labelled posts live in the markets database, but the video rubric is the
# AI channel's: only that channel checks clips.
if config.VIDEO_RUBRIC_PATH is None:
    config.VIDEO_RUBRIC_PATH = config.HERE / "channels" / "ai_news" / "video_rubric.md"

# (post id, image, expected, what the image is)
IMAGES = [
    (655, "https://pbs.twimg.com/media/HTjWcV2bwAAsvAt.jpg", "accept", "heatmap of the selloff"),
    (651, "https://pbs.twimg.com/media/HTjB4qXbQAANmcc.jpg", "accept", "grid of yield charts"),
    (647, "https://pbs.twimg.com/media/HTiy9rZacAAQDar.jpg", "accept", "Accenture price chart"),
    (643, "https://pbs.twimg.com/media/HTiUN4FbIAAqf2U.jpg", "accept", "dollar index chart"),
    (638, "https://pbs.twimg.com/media/HTh9j5FbwAAbkfY.jpg", "accept", "oil price chart"),
    (634, "https://pbs.twimg.com/media/HTg6TEEbMAAjFLx.jpg", "reject", "portrait of Japan's PM"),
    (631, "https://pbs.twimg.com/media/HTfU1kVXsAAaVZn.jpg", "reject", "Paramount logo"),
    (624, "https://pbs.twimg.com/media/HTeInaHbwAE63O9.jpg", "accept", "heatmap of the rally"),
    (621, "https://pbs.twimg.com/media/HTd3WNEa0AA6XTF.png", "accept", "BTC and ETH charts"),
    (619, "https://pbs.twimg.com/media/HTdufaVaYAAKv1g.jpg", "reject", "Fed's Barr at a podium"),
    (617, "https://pbs.twimg.com/media/HTasqT0XMAAQZ3l.jpg", "accept", "30-year yield chart"),
    (604, "https://pbs.twimg.com/media/HTTsoyqaIAA4rNX.jpg", "reject", "Trump and Xi shaking hands"),
    (599, "https://pbs.twimg.com/media/HTSAz-eXkAAK19Z.png", "accept", "Japan 2-year yield chart"),
    (597, "https://pbs.twimg.com/media/HTO4gNfa4AA__4J.jpg", "reject", "Nano Banc logo"),
    (596, "https://pbs.twimg.com/media/HTOkN2qWgAA_vVp.jpg", "reject", "Saudi crown prince portrait"),
    (594, "https://pbs.twimg.com/media/HTLN4BnXAAARles.jpg", "accept", "McDonald's chart with a Barchart logo"),
    (593, "https://pbs.twimg.com/media/HTKfXzfacAAaEVU.jpg", "accept", "Nasdaq chart"),
    (592, "https://pbs.twimg.com/media/HTFpjmZbQAA_TUU.jpg", "accept", "Apple price chart"),
    (589, "https://pbs.twimg.com/media/HTE0Tz3aMAAEitC.jpg", "accept", "oil price chart"),
    (584, "https://pbs.twimg.com/media/HTDGigUa4AADWYB.jpg", "reject", "stock photo of a tanker"),
    (583, "https://pbs.twimg.com/media/HTCK4MUbgAAyHF4.jpg", "reject", "Putin portrait"),
    (582, "https://pbs.twimg.com/media/HTBjrX6XkAAhKN8.jpg", "accept", "30-year yield chart"),
]

# (post id, several images, the one that should win or "" for none)
SETS = [
    (583, ["https://pbs.twimg.com/media/HTCK4MUbgAAyHF4.jpg",
           "https://pbs.twimg.com/media/HTDGigUa4AADWYB.jpg",
           "https://pbs.twimg.com/media/HTO4gNfa4AA__4J.jpg"], "", "portrait, stock photo, logo"),
    (638, ["https://pbs.twimg.com/media/HTOkN2qWgAA_vVp.jpg",
           "https://pbs.twimg.com/media/HTh9j5FbwAAbkfY.jpg"],
     "https://pbs.twimg.com/media/HTh9j5FbwAAbkfY.jpg", "portrait then the oil chart"),
]

# (video, post text, expected, what the pair tests)
VIDEOS = [
    ("https://video.twimg.com/amplify_video/2104600619977773056/vid/avc1/1920x1080/CkVdwlccYAQohPev.mp4",
     "Polymarket launches 15-minute Bitcoin price markets on its US app.",
     "accept", "the app's own launch clip"),
    ("https://video.twimg.com/amplify_video/2102147574534672385/vid/avc1/1920x1080/TT9XobnynUUlzndh.mp4",
     "X launches live stock market and crypto trading via cashtags on users' timelines.",
     "accept", "demo of the feature the post announces"),
    ("https://video.twimg.com/amplify_video/2102490512934739968/vid/avc1/1920x1080/YMlctJcEmyIQi3bg.mp4",
     "Your AI agent can now buy Glassnode data.",
     "accept", "the product clip behind the post"),
    ("https://video.twimg.com/amplify_video/2104600619977773056/vid/avc1/1920x1080/CkVdwlccYAQohPev.mp4",
     "Japan's 2-year government bond yield rises above 1.9%, the highest in 31 years.",
     "reject", "a betting-app ad on a bond yield post"),
    ("https://video.twimg.com/amplify_video/2102490512934739968/vid/avc1/1920x1080/YMlctJcEmyIQi3bg.mp4",
     "Saudi Arabia's oil exports hit their highest level since the Iran war began.",
     "reject", "a data-product clip on an oil post"),
]


def post_text(post_id: int) -> str:
    row = db.conn().execute("SELECT post_html FROM posts WHERE id = ?", (post_id,)).fetchone()
    return persona_loader.visible_text(row["post_html"]) if row else ""


async def labelled() -> int:
    wrong = 0
    print(f"IMAGES\n{LINE}")
    for post_id, url, expected, what in IMAGES:
        choice = await image_analyst.choose(post_text(post_id), [url])
        got = "failed" if choice.failed else ("accept" if choice.url == url else "reject")
        mark = "ok" if got == expected else "WRONG"
        wrong += mark != "ok"
        print(f"  [{expected}] {mark:5} {what}\n         {choice.reason[:110]}")

    print(f"\nSETS OF IMAGES\n{LINE}")
    for post_id, urls, best, what in SETS:
        choice = await image_analyst.choose(post_text(post_id), urls)
        mark = "ok" if (choice.url == best and not choice.failed) else "WRONG"
        wrong += mark != "ok"
        print(f"  {mark:5} {what}: chose {urls.index(choice.url) + 1 if choice.url else 'none'}")

    print(f"\nVIDEOS\n{LINE}")
    for url, text, expected, what in VIDEOS:
        choice = await video_analyst.choose(text, [{"url": url, "kind": "video"}])
        got = "failed" if choice.failed else ("accept" if choice.url == url else "reject")
        mark = "ok" if got == expected else "WRONG"
        wrong += mark != "ok"
        print(f"  [{expected}] {mark:5} {what}\n         {choice.reason[:110]}")

    total = len(IMAGES) + len(SETS) + len(VIDEOS)
    print(f"{LINE}\n   wrong {wrong}/{total}")
    return wrong


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labelled", action="store_true", help="score the labelled set")
    if not parser.parse_args().labelled:
        parser.print_help()
        return
    sys.exit(1 if asyncio.run(labelled()) else 0)


if __name__ == "__main__":
    main()
