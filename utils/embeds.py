"""Video players embedded in a page (Vimeo, YouTube): finding them, and downloading one
as an MP4 with yt-dlp so it can be judged and uploaded to Telegram.

Launch pages rarely link a video file; they embed a player. The download keeps to
720p and stops at MAX_VIDEO_MB, the most Telegram takes from a bot.
"""

from __future__ import annotations

import html as html_lib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from utils import logger as log_setup

log = log_setup.get("embeds")

# By full path: a systemd service does not search ~/.local/bin. Kept current by a
# weekly cron job (`crontab -l`), because sites change and yt-dlp breaks until updated.
YTDLP = shutil.which("yt-dlp") or str(Path.home() / ".local/bin/yt-dlp")

ALERT_AFTER_FAILURES = 3
_failures = 0

# Matched in the raw page, scripts included, because players are often only in JSON.
_PLAYER = re.compile(
    r"https?:(?:\\?/){2}(player\.vimeo\.com(?:\\?/)video(?:\\?/)\d+(?:\?h=[0-9a-f]+)?"
    r"|www\.youtube(?:-nocookie)?\.com(?:\\?/)embed(?:\\?/)[\w-]{11})")


def find(page_html: str) -> list[str]:
    """Every distinct player address on the page, in the order they appear."""
    found: list[str] = []
    for match in _PLAYER.finditer(html_lib.unescape(page_html or "")):
        url = "https://" + match.group(1).replace("\\/", "/")
        url = url.replace("youtube-nocookie.com", "youtube.com")
        if url not in found:
            found.append(url)
    return found


def download(url: str, max_mb: int) -> Path | None:
    """Download one player's video to a temporary MP4. None if it fails or is too big."""
    folder = Path(tempfile.mkdtemp(prefix="clip-"))
    target = folder / "clip.mp4"
    try:
        subprocess.run(
            [YTDLP, "-q", "--no-warnings", "--no-playlist",
             "-f", "bv*[height<=720]+ba/bv*[height<=720]/b[height<=720]/b",
             "--merge-output-format", "mp4", "--max-filesize", f"{max_mb}M",
             "-o", str(target), url],
            capture_output=True, text=True, timeout=180, check=True)
    except (subprocess.SubprocessError, OSError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        log.info("Could not download %s: %s", url[:80], detail[-300:])
        shutil.rmtree(folder, ignore_errors=True)
        _failed(detail)
        return None
    if not target.exists():
        # yt-dlp skips a file over --max-filesize without an error: too big, not broken.
        shutil.rmtree(folder, ignore_errors=True)
        return None
    global _failures
    _failures = 0
    return target


def _failed(detail: str) -> None:
    """Count a failed download; say so once when they keep failing in a row."""
    global _failures
    _failures += 1
    if _failures == ALERT_AFTER_FAILURES:
        from utils import telegram_error
        telegram_error.send_error(
            f"Video downloads have failed {_failures} times in a row, so posts are going "
            f"out without their clips. Usually yt-dlp needs updating: "
            f"/home/nikita/miniconda3/bin/python3 -m pip install -U yt-dlp\n"
            f"Last error: {detail[-300:]}", node_name="embeds")
