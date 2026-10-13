"""Tests for follow-up posts, the sifter and the digest cutoff (SPEC.md, 2026-10-13 section).

Every model and embedding call is faked. They check the FAILURE lines code decides: related
posts reach the writer and the editor, unrelated ones do not, a memory outage makes the item
wait, repeated phrasing gets one rewrite, and the digest never releases an item held after it.
Run: /usr/bin/python3 tests/test_follow_ups.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

config.DB_PATH = Path(tempfile.mkdtemp()) / "test.db"

from utils import db, semantic_memory  # noqa: E402

db.init_db()

PASSED: list[str] = []
FAILED: list[str] = []

FIRST = ("<b>Meta's Muse Wonder is a new AI that plans and runs long coding jobs</b>\n\n"
         "It splits the work across many agents at once and is only for Muse Code subscribers.")
SECOND = ("<b>Meta's new Muse Wonder AI is now the second-best model on a major test list</b>\n\n"
          "It scored just two points behind Claude Opus 5.5.")
UNRELATED = "<b>OpenAI's GPT-6.1 Sol can now read much more text at once</b>"


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


def _item(title: str, *, company: str = "Meta", status: str = "queued") -> int:
    n = db.conn().execute("SELECT COUNT(*) FROM items").fetchone()[0]
    item_id = db.insert_item(origin="rss", source_name="futuretools", external_id=f"f{n}",
                             url=f"https://e.x/{n}", title=title, body=f"{title}. " * 20,
                             status=status)
    db.conn().execute("UPDATE items SET company = ?, topic = 'new_model', importance = 4 "
                      "WHERE id = ?", (company, item_id))
    db.conn().commit()
    return item_id


def _fake_matches(found):
    async def fake(text, *, now=None, persist=True):
        if isinstance(found, Exception):
            raise found
        return [dict(row) for row in found]
    return fake


MATCHES = [
    {"id": 78, "text": SECOND, "sent_at": "2026-10-12 17:12:47", "score": 0.817},
    {"id": 77, "text": FIRST, "sent_at": "2026-10-12 16:43:59", "score": 0.808},
    {"id": 25, "text": UNRELATED, "sent_at": "2026-10-11 23:54:29", "score": 0.64},
]


@test
async def only_posts_about_the_same_thing_count_as_related():
    from nodes import follow_up
    real, semantic_memory.published_matches = semantic_memory.published_matches, _fake_matches(MATCHES)
    try:
        found = await follow_up.related_posts(dict(db.get_item(_item("Meta Launches Muse Wonder"))))
    finally:
        semantic_memory.published_matches = real
    assert [p["id"] for p in found] == [78, 77], found


SOURCE_OLD = "Muse Wonder is available today via the Meta Model API and Muse Code."
SOURCE_NEW = "Active Memory carries your details from one chat to the next."


def _meta_item() -> int:
    item_id = _item("Meta Launches Muse Wonder")
    db.conn().execute("UPDATE items SET body = ? WHERE id = ?",
                      (f"{SOURCE_OLD} {SOURCE_NEW}", item_id))
    db.conn().commit()
    return item_id


def _fake_sifter(answer):
    """Stand-in for the sifter's model call: an answer dict, or an exception to raise."""
    calls = []

    async def fake(**kwargs):
        calls.append(kwargs)
        if isinstance(answer, Exception):
            raise answer
        return answer
    return fake, calls


async def _sift(state_extra: dict, matches, answer):
    from pipeline import stations
    from utils import openrouter
    fake, calls = _fake_sifter(answer)
    real = semantic_memory.published_matches, openrouter.chat_json
    semantic_memory.published_matches, openrouter.chat_json = _fake_matches(matches), fake
    try:
        state = await stations.sifter_node(state_extra)
    finally:
        semantic_memory.published_matches, openrouter.chat_json = real
    return state, calls


NEW_FACT = {"fact": "Active Memory remembers details across chats", "quote": SOURCE_NEW}


@test
async def the_sifter_passes_on_only_quoted_new_facts():
    invented = {"fact": "a Nano version is coming", "quote": "Muse Wonder Nano ships next week"}
    item_id = _meta_item()
    state, calls = await _sift({"item": dict(db.get_item(item_id))}, MATCHES,
                               {"new_facts": [NEW_FACT, invented], "worth_a_post": True,
                                "reason": "memory is new"})
    assert len(calls) == 1
    assert state.get("related_posts") == [SECOND, FIRST]
    assert state.get("new_facts") == [NEW_FACT], state.get("new_facts")
    assert not state.get("outcome")


@test
async def nothing_new_means_the_item_is_held_and_never_written():
    from pipeline import stations
    item_id = _meta_item()
    state, _ = await _sift({"item": dict(db.get_item(item_id))}, MATCHES,
                           {"new_facts": [], "reason": "both posts already said all of it"})
    assert state.get("outcome") == "nothing_new", state
    assert stations.route_after_sifter(state) == "nothing new"
    row = db.get_item(item_id)
    assert row["status"] == "held" and "already said" in row["status_reason"], dict(row)


@test
async def new_but_only_trivia_is_held_too():
    from pipeline import stations
    item_id = _meta_item()
    state, _ = await _sift({"item": dict(db.get_item(item_id))}, MATCHES,
                           {"new_facts": [NEW_FACT], "worth_a_post": False,
                            "reason": "only background on how it was built"})
    assert state.get("outcome") == "nothing_new", state
    assert stations.route_after_sifter(state) == "nothing new"
    row = db.get_item(item_id)
    assert row["status"] == "held" and "worth a new post" in row["status_reason"], dict(row)


@test
async def no_related_posts_means_no_sifting_and_a_normal_post():
    from pipeline import stations
    item_id = _item("Something nobody covered")
    state, calls = await _sift({"item": dict(db.get_item(item_id))}, MATCHES[2:], {})
    assert calls == [] and state == {"related_posts": [], "new_facts": []}, state
    assert stations.route_after_sifter(state) == "new facts"


@test
async def memory_down_means_the_item_waits():
    item_id = _meta_item()
    state, calls = await _sift({"item": dict(db.get_item(item_id))},
                               semantic_memory.Unavailable("embeddings down"), {})
    assert state.get("outcome") == "retry" and calls == [], state
    assert db.get_item(item_id)["status"] == "queued"


@test
async def a_sifter_outage_falls_back_to_a_prompt_only_follow_up():
    item_id = _meta_item()
    state, _ = await _sift({"item": dict(db.get_item(item_id))}, MATCHES, RuntimeError("model down"))
    assert not state.get("outcome")
    assert state.get("related_posts") == [SECOND, FIRST] and state.get("new_facts") == []


@test
async def only_invented_quotes_counts_as_an_outage_not_as_nothing_new():
    bad = {"fact": "x", "quote": "words that are nowhere in the source"}
    item_id = _meta_item()
    state, _ = await _sift({"item": dict(db.get_item(item_id))}, MATCHES,
                           {"new_facts": [bad], "reason": "r"})
    assert not state.get("outcome") and state.get("new_facts") == []
    assert db.get_item(item_id)["status"] != "held"


@test
async def a_forced_item_gets_the_earlier_posts_but_is_never_sifted():
    item_id = _meta_item()
    state, calls = await _sift({"item": dict(db.get_item(item_id)), "forced": True}, MATCHES,
                               {"new_facts": [], "reason": "nothing new"})
    assert calls == [] and not state.get("outcome")
    assert state.get("related_posts") == [SECOND, FIRST]


@test
async def a_digest_skips_the_sifter():
    item_id = _meta_item()
    state, calls = await _sift({"item": dict(db.get_item(item_id)), "digest": True},
                               RuntimeError("must not search"), {})
    assert calls == [] and state == {"related_posts": [], "new_facts": []}, state


@test
def the_sifter_sits_between_the_company_limit_and_the_writer():
    from pipeline import graph
    edges = {(e.source, e.target) for e in graph.graph.get_graph().edges}
    assert ("company_limit", "sifter") in edges and ("sifter", "writer") in edges, edges
    assert ("company_limit", "writer") not in edges


@test
async def the_writer_gets_the_new_facts_and_not_the_source():
    from nodes import writer
    from utils import openrouter
    item_id = _meta_item()
    prompts = []

    async def fake_text(*, model, system, user, **kwargs):
        prompts.append(user)
        return "<b>Muse Wonder now remembers you between chats</b>"
    real, openrouter.chat_text = openrouter.chat_text, fake_text
    try:
        await writer.execute(dict(db.get_item(item_id)), related_posts=[FIRST],
                             new_facts=[NEW_FACT])
    finally:
        openrouter.chat_text = real
    assert SOURCE_NEW in prompts[0] and FIRST in prompts[0]
    assert SOURCE_OLD not in prompts[0], "the old facts must not reach the writer"
    assert "Meta Launches Muse Wonder" not in prompts[0], "nor the source's launch headline"


@test
async def the_writer_station_passes_on_what_the_sifter_found():
    from nodes import writer
    from pipeline import stations
    item_id = _meta_item()
    seen = {}

    async def fake_write(item, **kwargs):
        seen.update(kwargs)
        return "<b>Muse Wonder now remembers you</b>"
    real = semantic_memory.published_matches, writer.execute
    semantic_memory.published_matches = _fake_matches(RuntimeError("the writer must not search"))
    writer.execute = fake_write
    try:
        state = await stations.writer_node({"item": dict(db.get_item(item_id)),
                                            "related_posts": [FIRST], "new_facts": [NEW_FACT]})
    finally:
        semantic_memory.published_matches, writer.execute = real
    assert seen.get("related_posts") == [FIRST] and seen.get("new_facts") == [NEW_FACT]
    assert state.get("post_html")


@test
async def the_editor_sees_the_related_posts():
    from nodes import editor
    from pipeline import stations
    seen = {}

    async def fake_editor(item, post_html, post_id, **kwargs):
        seen.update(kwargs)
        return {"approved": True, "rules_broken": [], "reason": "", "confidence": 0.9, "error": False}
    real, editor.execute = editor.execute, fake_editor
    try:
        await stations.editor_node({"item": dict(db.get_item(_item("Meta Launches Muse Wonder"))),
                                    "post_html": "<b>x</b>", "post_id": 1,
                                    "related_posts": [SECOND, FIRST]})
    finally:
        editor.execute = real
    assert FIRST in seen.get("parent_post", "") and SECOND in seen["parent_post"]


@test
def shared_phrases_are_found_and_names_alone_are_not():
    from nodes import follow_up
    new = "<b>Muse Wonder now remembers you</b>\n\nIt is only for Muse Code subscribers, for now."
    assert follow_up.shared_phrases(new, [FIRST]) == ["is only for muse code subscribers"]
    assert follow_up.shared_phrases("<b>Muse Wonder now remembers you</b>", [FIRST]) == []
    ends = "<b>Full is for Muse Code</b>\n<a href='L'>subscribers read the announcement here</a>"
    assert follow_up.shared_phrases(ends, ["only for Muse Code\nsubscribers read the announcement"]) == []


@test
async def a_post_that_reuses_a_related_posts_words_gets_one_rewrite():
    from nodes import writer
    from utils import openrouter
    item_id = _item("Meta Launches Muse Wonder")
    drafts = ["<b>Meta's Muse Wonder is a new AI that plans and runs long coding jobs</b>",
              "<b>Muse Wonder can now remember details between chats</b>"]
    prompts = []

    async def fake_text(*, model, system, user, **kwargs):
        prompts.append((system, user))
        return drafts[len(prompts) - 1]
    real, openrouter.chat_text = openrouter.chat_text, fake_text
    try:
        post = await writer.execute(dict(db.get_item(item_id)), related_posts=[FIRST])
    finally:
        openrouter.chat_text = real
    assert len(prompts) == 2, len(prompts)
    assert "Muse Wonder can now remember" in post
    assert FIRST in prompts[0][1], "the related post must be next to the source"


# ── the digest cutoff ───────────────────────────────────────────────────────

def _waiting(title: str, company: str, since: datetime) -> int:
    item_id = _item(title, company=company, status="waiting_digest")
    stamp = since.strftime("%Y-%m-%d %H:%M:%S")
    db.conn().execute("UPDATE items SET updated_at = ?, fetched_at = ? WHERE id = ?",
                      (stamp, stamp, item_id))
    db.conn().commit()
    return item_id


@test
async def an_item_held_after_the_digest_hour_waits_for_tomorrow():
    from nodes import company_digest
    from pipeline import graph
    db.conn().execute("UPDATE items SET status='expired' WHERE status='waiting_digest'")
    db.conn().execute("DELETE FROM posts")
    db.conn().execute("DELETE FROM meta WHERE key LIKE 'digest:%'")
    db.conn().commit()
    today = datetime.now(timezone.utc).replace(hour=config.DIGEST_HOUR_UTC, minute=0,
                                               second=0, microsecond=0) - timedelta(days=1)
    early = _waiting("held before the digest", "Google", today - timedelta(hours=2))
    late = _waiting("held after the digest", "Meta", today + timedelta(minutes=29))
    calls = []

    async def fake_run(item, **kwargs):
        calls.append(item["id"])
        db.set_item_status(item["id"], "published", "sent")
        return {"outcome": "published"}
    real, graph.run_item = graph.run_item, fake_run
    try:
        await company_digest.run_due(today + timedelta(minutes=31))
        assert calls == [early], calls
        await company_digest.run_due(today + timedelta(days=1, minutes=1))
    finally:
        graph.run_item = real
    assert calls == [early, late], calls


@test
def a_waiting_item_does_not_expire_before_its_digest():
    db.conn().execute("UPDATE items SET status='expired' WHERE status='waiting_digest'")
    db.conn().commit()
    item_id = _waiting("fetched long ago, held recently", "Meta",
                       datetime.now(timezone.utc) - timedelta(hours=2))
    db.conn().execute("UPDATE items SET fetched_at = datetime('now', '-40 hours') WHERE id = ?",
                      (item_id,))
    db.conn().commit()
    db.expire_digest_waits(config.DIGEST_MAX_WAIT_HOURS)
    assert db.get_item(item_id)["status"] == "waiting_digest"
    stale = _waiting("waiting for days", "Meta",
                     datetime.now(timezone.utc) - timedelta(hours=config.DIGEST_MAX_WAIT_HOURS + 1))
    db.expire_digest_waits(config.DIGEST_MAX_WAIT_HOURS)
    assert db.get_item(stale)["status"] == "expired"


print(f"{len(PASSED)} passed, {len(FAILED)} failed")
for line in FAILED:
    print("  FAIL", line[:240])
sys.exit(1 if FAILED else 0)
