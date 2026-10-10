"""Tests for the labels, the retired stories, the 7-day duplicate window and the company digest.

Every model call is faked. They check the SPEC.md FAILURE lines that code decides:
labels stay on the fixed lists, roundups never reach the writer, no story station runs,
a company's third post waits for the evening digest, and the digest goes out once a day.
Run: /usr/bin/python3 tests/test_labels_and_digest.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

config.DB_PATH = Path(tempfile.mkdtemp()) / "test.db"

from utils import db  # noqa: E402

db.init_db()

PASSED: list[str] = []
FAILED: list[str] = []


def test(fn):
    """Run one test, sync or async, and record whether it passed."""
    try:
        result = fn()
        if asyncio.iscoroutine(result):
            asyncio.run(result)
        PASSED.append(fn.__name__)
    except Exception as error:  # noqa: BLE001
        FAILED.append(f"{fn.__name__}: {type(error).__name__} {error}")
    return fn


def _item(title: str, *, company: str = "", kind: str = "", status: str = "queued",
          importance: int = 4, hours_ago: float = 0) -> int:
    n = db.conn().execute("SELECT COUNT(*) FROM items").fetchone()[0]
    item_id = db.insert_item(origin="rss", source_name="openai", external_id=f"i{n}",
                             url=f"https://e.x/{n}", title=title, body=f"{title}. " * 30,
                             status=status)
    db.conn().execute(
        "UPDATE items SET company = ?, topic = ?, importance = ?, "
        "fetched_at = datetime('now', ?) WHERE id = ?",
        (company, kind, importance, f"-{int(hours_ago * 60)} minutes", item_id))
    db.conn().commit()
    return item_id


def _sent(company: str, minutes_ago: int = 0) -> None:
    item_id = _item(f"sent {company}", company=company, kind="feature", status="published")
    post_id = db.create_post(item_id=item_id, topic="feature", post_html="<b>x</b>",
                             image_url="", writer_model="t")
    db.conn().execute("UPDATE posts SET status='sent', sent_at=datetime('now', ?) WHERE id=?",
                      (f"-{minutes_ago} minutes", post_id))
    db.conn().commit()


# ── Labels come from fixed lists ──

@test
def the_lists_are_fixed_and_end_in_other():
    from nodes import labeler
    assert config.KINDS == ("new_product", "new_model", "feature", "pricing", "tool",
                            "skill", "guide", "roundup", "other")
    assert config.COMPANIES[-1] == "other" and "Anthropic" in config.COMPANIES
    assert labeler.clean("new-model", "Open-AI") == ("other", "other")
    assert labeler.clean("new_model", "openai") == ("new_model", "OpenAI")
    assert labeler.clean("", None) == ("other", "other")


@test
async def an_answer_off_the_list_is_stored_as_other():
    from nodes import labeler
    from utils import openrouter
    answers = iter([{"kind": "product launch", "company": "Anthropic PBC", "reason": "x"},
                    RuntimeError("down")])

    async def fake(**kwargs):
        assert kwargs["model"] == config.LABELER_MODEL
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer
    real, openrouter.chat_json = openrouter.chat_json, fake
    item_id = _item("Claude gets a thing")
    try:
        first = await labeler.execute(dict(db.get_item(item_id)))
        second = await labeler.execute(dict(db.get_item(item_id)))
    finally:
        openrouter.chat_json = real
    assert (first["kind"], first["company"]) == ("other", "other") and not first["failed"]
    assert (second["kind"], second["company"]) == ("other", "other") and second["failed"]


@test
async def a_roundup_is_dropped_before_the_sorter():
    from nodes import labeler, sorter
    from pipeline import stations

    async def fake_label(item):
        return {"kind": "roundup", "company": "other", "reason": "a daily brief", "failed": False}

    async def no_sorter(item):
        raise AssertionError("the sorter must not see a roundup")
    real = labeler.execute, sorter.execute
    labeler.execute, sorter.execute = fake_label, no_sorter
    item_id = _item("DAILY AI BRIEF — Oct 9")
    try:
        state = await stations.labeler_node({"item": dict(db.get_item(item_id))})
    finally:
        labeler.execute, sorter.execute = real
    assert state.get("outcome") == "roundup", state
    row = db.get_item(item_id)
    assert row["status"] == "irrelevant" and "roundup" in row["status_reason"]
    assert row["topic"] == "roundup"


@test
async def labels_are_stored_and_carried_to_the_sorter():
    from nodes import labeler, sorter
    from pipeline import stations

    async def fake_label(item):
        return {"kind": "new_model", "company": "Anthropic", "reason": "Haiku 5.5", "failed": False}
    real, labeler.execute = labeler.execute, fake_label
    item_id = _item("Haiku 5.5 is here")
    try:
        state = await stations.labeler_node({"item": dict(db.get_item(item_id))})
    finally:
        labeler.execute = real
    assert not state.get("outcome")
    assert state["item"]["topic"] == "new_model" and state["item"]["company"] == "Anthropic"
    row = db.get_item(item_id)
    assert (row["topic"], row["company"]) == ("new_model", "Anthropic")
    message = sorter.user_message(state["item"])
    assert "new_model" in message and "Anthropic" in message
    assert "topic" not in sorter.SCHEMA["required"]


# ── Stories are off; the duplicate check looks back a week ──

@test
def no_story_station_is_in_the_graph():
    from pipeline import graph
    assert config.STORIES is False
    nodes = set(graph.graph.get_graph().nodes)
    assert not {"story_organizer", "gatekeeper"} & nodes, nodes
    edges = {(e.source, e.target) for e in graph.graph.get_graph().edges}
    for pair in [("fetch_article", "labeler"), ("labeler", "sorter"),
                 ("sorter", "company_limit"), ("company_limit", "writer")]:
        assert pair in edges, (pair, edges)


@test
def the_dashboard_lists_the_same_stations_as_the_graph():
    from pipeline import graph
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboard" / "backend"))
    import paths
    nodes = [n for n in graph.graph.get_graph().nodes if not n.startswith("__")]
    assert list(paths.STATIONS) == nodes, (paths.STATIONS, nodes)


@test
def the_duplicate_check_looks_back_a_week():
    assert config.DUPLICATE_MAX_GAP_HOURS >= 168 and config.COSINE_WINDOW_HOURS >= 168
    assert config.FUZZY_WINDOW_HOURS == 24     # "DAILY AI BRIEF — Oct 7" vs "Oct 8" read alike


@test
async def a_repeat_of_a_published_item_is_dropped_and_of_a_rejected_one_let_through():
    from nodes import dedup
    from pipeline import stations
    published = _item("GPT-6 for everyone", status="published", hours_ago=72)
    rejected = _item("GPT-6 maybe", status="low_impact", hours_ago=72)
    matches = iter([published, rejected])

    async def fake_classify(item, **kwargs):
        return "duplicate", next(matches), 0.80
    real, dedup.classify = dedup.classify, fake_classify
    first, second = _item("GPT-6 rolls out"), _item("GPT-6 now live")
    try:
        dropped = await stations.dedup_node({"item": dict(db.get_item(first))})
        through = await stations.dedup_node({"item": dict(db.get_item(second))})
    finally:
        dedup.classify = real
    assert dropped.get("outcome") == "duplicate" and db.get_item(first)["status"] == "duplicate"
    assert db.get_item(first)["story_id"] is None
    assert not through.get("outcome") and db.get_item(second)["status"] == "queued"


# ── A company's third post of the day waits for the digest ──

@test
async def a_company_gets_two_posts_a_day_and_a_five_always_goes():
    from nodes import company_digest
    from pipeline import stations
    db.conn().execute("DELETE FROM posts"); db.conn().commit()
    assert company_digest.limit_reason("Anthropic", 4) == ""
    _sent("Anthropic"); _sent("Anthropic")
    _sent("Anthropic", minutes_ago=60 * 30)                       # yesterday's does not count
    assert "2" in company_digest.limit_reason("Anthropic", 4)
    assert company_digest.limit_reason("Anthropic", 5) == ""      # a big launch always posts
    assert company_digest.limit_reason("OpenAI", 4) == ""
    assert company_digest.limit_reason("other", 4) == ""          # independents are not limited
    item_id = _item("Claude Dashboards", company="Anthropic", kind="new_product")
    state = await stations.company_limit_node({"item": dict(db.get_item(item_id))})
    assert state.get("outcome") == "waiting_digest"
    assert db.get_item(item_id)["status"] == "waiting_digest"
    forced = await stations.company_limit_node({"item": dict(db.get_item(item_id)), "forced": True})
    assert not forced.get("outcome")


@test
async def the_digest_goes_out_once_a_day_at_its_hour():
    from nodes import company_digest
    from pipeline import graph
    db.conn().execute("UPDATE items SET status='expired' WHERE status='waiting_digest'")
    db.conn().execute("DELETE FROM posts")      # a post a moment ago would make the digest wait its turn
    db.conn().commit()
    waiting = [_item(f"Anthropic thing {n}", company="Anthropic", kind="feature",
                     status="waiting_digest", hours_ago=2) for n in range(3)]
    lone = _item("OpenAI thing", company="OpenAI", kind="feature", status="waiting_digest", hours_ago=2)
    old = _item("Ancient thing", company="Google", kind="feature", status="waiting_digest",
                hours_ago=config.DIGEST_MAX_WAIT_HOURS + 1)
    calls = []

    async def fake_run(item, **kwargs):
        calls.append((dict(item), kwargs))
        return {"outcome": "published"}
    real, graph.run_item = graph.run_item, fake_run
    day = datetime.now(timezone.utc).date()
    before = datetime(day.year, day.month, day.day, config.DIGEST_HOUR_UTC - 1, 30, tzinfo=timezone.utc)
    after = datetime(day.year, day.month, day.day, config.DIGEST_HOUR_UTC, 30, tzinfo=timezone.utc)
    try:
        await company_digest.run_due(before)
        assert calls == []
        await company_digest.run_due(after)
        await company_digest.run_due(after)                       # second call that day: nothing
    finally:
        graph.run_item = real
    assert len(calls) == 2, [c[1] for c in calls]
    digest = next(c for c in calls if c[1].get("digest"))
    assert sorted(digest[1]["digest_item_ids"]) == sorted(waiting)
    assert "Anthropic" in digest[1]["brief"] and "3" in digest[1]["brief"]
    assert all(f"Anthropic thing {n}" in digest[0]["body"] for n in range(3))
    single = next(c for c in calls if not c[1].get("digest"))
    assert single[0]["id"] == lone and single[1].get("released")
    assert db.get_item(old)["status"] == "expired"


@test
async def a_sent_digest_marks_its_other_items_as_covered():
    from nodes import publisher
    from pipeline import stations
    ids = [_item(f"Google thing {n}", company="Google", status="waiting_digest") for n in range(3)]
    sent = {}

    async def fake_execute(item, html, post_id, reply_to_message_id=None):
        sent["reply_to"] = reply_to_message_id
        sent["item"] = item
        return True
    real, publisher.execute = publisher.execute, fake_execute
    try:
        state = await stations.publish_node({
            "item": {"id": ids[-1], "url": "https://x.com/a/status/1", "link_url": ""},
            "post_html": "<b>More from Google today</b>", "post_id": 1,
            "digest": True, "digest_item_ids": ids})
    finally:
        publisher.execute = real
    assert state["outcome"] == "published" and sent["reply_to"] is None
    assert [db.get_item(i)["status"] for i in ids[:-1]] == ["merged", "merged"]
    assert "digest" in db.get_item(ids[0])["status_reason"]


print(f"{len(PASSED)} passed, {len(FAILED)} failed")
for line in FAILED:
    print("  FAIL", line[:240])
sys.exit(1 if FAILED else 0)
