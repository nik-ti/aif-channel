"""GET /api/v1/graph — the pipeline's stations in order, plus live health per
station (last invocation time, error count) read from the database every request.
Stations without a dedicated health query report zero errors and an unknown last
invocation. With no database yet it returns "ready": false.
"""

from __future__ import annotations

from fastapi import APIRouter

import paths
from db_connector import query, query_one

router = APIRouter()

# What each station is called and what it does, for the diagram.
_STATION_INFO: dict[str, tuple[str, str]] = {
    "dedup": ("Dedup", "Have we already covered this? Five checks, ending in an LLM that reads both texts."),
    "fetch_article": ("Fetch article", "Reads the full page BEFORE the sorter (plain, then browser, then reader service), finds the product link, pictures and video players."),
    "sorter": ("Sorter", "Can a regular person use this today? Scores usefulness 1-5; the bar is 4. 'Nobody can use it' caps at 3."),
    "story_organizer": ("Story organizer", "One product = one story. Same company or same event is not enough."),
    "gatekeeper": ("Gatekeeper", "Has the story moved? Post, hold, or this is the wrong story."),
    "writer": ("Writer", "Bold first line, • lines, bold key words, link last. No emoji. Simple enough for a 12-year-old."),
    "editor": ("Editor", "Checks the post against the source, including JARGON. Sees its own earlier reason on the rewrite."),
    "repeat_check": ("Repeat check", "The exit. Refuses a finished post that tells the reader what a recent post already did."),
    "image_analyst": ("Image analyst", "Chooses the one picture that goes with the post, or none. A failure means no picture."),
    "video_analyst": ("Video analyst", "Downloads clips and video players (yt-dlp) and keeps one that shows what the post says. Over 2 minutes is refused unseen."),
    "publish": ("Publish", "Fills in the product link, adds the 'AI Flow | Subscribe' signature, sends with the chosen media."),
}


def _station_info(node_id: str) -> tuple[str, str]:
    return _STATION_INFO.get(node_id, (node_id.replace("_", " "), ""))


def _sum_counter(*kinds: str) -> int:
    if not kinds:
        return 0
    placeholders = ",".join("?" for _ in kinds)
    row = query_one(
        f"SELECT COALESCE(SUM(n), 0) AS total FROM counters WHERE kind IN ({placeholders})",
        kinds,
    )
    return row["total"] if row else 0


def _max_value(table: str, column: str, where: str = "") -> str | None:
    row = query_one(f"SELECT MAX({column}) AS v FROM {table} {where}")
    return row["v"] if row else None


def _health(error_count: int) -> str:
    if error_count == 0:
        return "ok"
    if error_count <= 3:
        return "degraded"
    return "error"


# node id -> a function computing its health dict, for the nodes this
# dashboard knows how to measure. Anything else falls back to the neutral default below.
def _known_node_health(node_id: str) -> dict | None:
    if node_id == "dedup":
        return {
            "last_invocation": _max_value("items", "fetched_at"),
            "error_count": _sum_counter("judge_error", "meaning_check_failed"),
        }
    if node_id == "sorter":
        return {"last_invocation": _max_value("items", "updated_at"), "error_count": 0}
    if node_id == "fetch_article":
        return {
            "last_invocation": _max_value("items", "updated_at", "WHERE article_text != ''"),
            "error_count": 0,
        }
    if node_id == "story_organizer":
        return {
            "last_invocation": _max_value("items", "updated_at", "WHERE story_id IS NOT NULL"),
            "error_count": _sum_counter("story_place_failed"),
        }
    if node_id == "gate":
        return {"last_invocation": _max_value("stories", "last_item_at"), "error_count": 0}
    if node_id == "writer":
        failed = query_one("SELECT COUNT(*) AS n FROM items WHERE status = 'failed'")
        return {
            "last_invocation": _max_value("posts", "created_at"),
            "error_count": failed["n"] if failed else 0,
        }
    if node_id == "editor":
        return {"last_invocation": _max_value("editor_decisions", "created_at"), "error_count": 0}
    if node_id == "publish":
        send_failed = query_one("SELECT COUNT(*) AS n FROM posts WHERE status = 'send_failed'")
        return {
            "last_invocation": _max_value("posts", "sent_at", "WHERE status = 'sent'"),
            "error_count": send_failed["n"] if send_failed else 0,
        }
    return None


@router.get("/graph")
def get_graph():

    if not paths.database_ready():
        return {"ready": False, "nodes": [], "edges": []}

    node_ids = list(paths.STATIONS)

    nodes = []
    for node_id in node_ids:
        health = _known_node_health(node_id) or {"last_invocation": None, "error_count": 0}
        nodes.append(
            {
                "id": node_id,
                "label": _station_info(node_id)[0],
                "description": _station_info(node_id)[1],
                "last_invocation": health["last_invocation"],
                "error_count": health["error_count"],
                "health": _health(health["error_count"]),
            }
        )
    edges = [{"source": a, "target": b} for a, b in zip(node_ids, node_ids[1:])]

    return {"ready": True, "nodes": nodes, "edges": edges}
