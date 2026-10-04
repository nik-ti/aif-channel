"""Collects every image and video a post could carry, for the analysts to judge.

Candidates come from each item the post was written from: all of a tweet's
images and its clip, and on channels with COLLECT_ARTICLE_MEDIA also the images
and video files on the article page. Nothing here decides what goes out; see
nodes/image_analyst.py and nodes/video_analyst.py.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

# Page furniture, not illustrations. Matched against the image address.
_FURNITURE = re.compile(
    r"avatar|gravatar|icon|logo|sprite|emoji|badge|pixel|spacer|tracking|"
    r"/ads?/|doubleclick|placeholder|blank\.", re.IGNORECASE)
_MIN_SIDE = 200          # pixels, when the page states a size
_MAX_FROM_PAGE = 10
_VIDEO_FILE = re.compile(r"\.(mp4|webm|mov)(\?|$)", re.IGNORECASE)


@dataclass
class Candidates:
    images: list[str] = field(default_factory=list)
    videos: list[dict] = field(default_factory=list)     # {"url", "kind": "video"|"gif"}


def _get(item, key: str, default=""):
    """A field from a dict or a database row, or the default if it has none."""
    try:
        value = item[key]
    except (KeyError, IndexError):
        return default
    return default if value is None else value


def _from_row(item) -> Candidates:
    found = Candidates()
    raw = _get(item, "media_json")
    if raw:
        try:
            stored = json.loads(raw)
            found.images = [u for u in stored.get("images", []) if u]
            found.videos = [v for v in stored.get("videos", []) if v.get("url")]
        except (ValueError, AttributeError):
            pass
    # Rows from before media_json existed still carry their one image and clip.
    image = _get(item, "image_url")
    if image and image not in found.images:
        found.images.insert(0, image)
    video = _get(item, "video_url")
    if video and video not in {v["url"] for v in found.videos}:
        found.videos.insert(0, {"url": video, "kind": _get(item, "video_kind") or "video"})
    return found


def merge(items) -> dict:
    """Every item's candidates in one list, newest item first, no repeats."""
    images, videos, seen = [], [], set()
    for item in reversed(list(items)):
        found = _from_row(item)
        for url in found.images:
            if url not in seen:
                seen.add(url)
                images.append(url)
        for video in found.videos:
            if video["url"] not in seen:
                seen.add(video["url"])
                videos.append(video)
    return {"images": images, "videos": videos}


def candidates(item) -> Candidates:
    """What this post could carry. A folded story source brings its items' media with it."""
    folded = _get(item, "candidate_media", None)
    if folded:
        return Candidates(images=list(folded.get("images", [])),
                          videos=list(folded.get("videos", [])))
    return _from_row(item)


def _too_small(tag) -> bool:
    for side in ("width", "height"):
        value = str(tag.get(side, "")).strip().rstrip("px")
        if value.isdigit() and int(value) < _MIN_SIDE:
            return True
    return False


def from_article_html(html: str, page_url: str) -> tuple[list[str], list[dict]]:
    """The illustrations and video files on an article page: (images, videos)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "lxml")
    images: list[str] = []
    videos: list[dict] = []

    seen_paths: set[str] = set()

    def keep_image(src: str) -> None:
        if not src or src.startswith("data:"):
            return
        url = urljoin(page_url, src.strip())
        # One picture under several crops (?resize=, ?w=) is still one picture.
        path = url.split("?")[0]
        if (url.startswith("http") and path not in seen_paths
                and not _FURNITURE.search(path) and not path.lower().endswith((".svg", ".gif"))):
            seen_paths.add(path)
            images.append(url)

    # The page's own choice of picture for itself, when it made one.
    for name in ("og:image", "twitter:image"):
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            keep_image(tag["content"])

    body = soup.find("article") or soup.find("main") or soup.body or soup
    for tag in body.find_all("img"):
        if _too_small(tag):
            continue
        keep_image(tag.get("src") or tag.get("data-src") or "")

    for tag in body.find_all(["video", "source"]):
        src = urljoin(page_url, (tag.get("src") or "").strip())
        if _VIDEO_FILE.search(src) and src not in {v["url"] for v in videos}:
            videos.append({"url": src, "kind": "video"})

    # Launch pages embed a player more often than they link a file.
    from utils import embeds
    for url in embeds.find(html):
        if url not in {v["url"] for v in videos}:
            videos.append({"url": url, "kind": "embed"})

    return images[:_MAX_FROM_PAGE], videos[:4]
