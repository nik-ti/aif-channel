"""Backfill the persistent cache, or rehearse reader memory on a private DB copy.

No command sends channel messages. Only --backfill writes to the channel DB;
the incident and labelled checks use an SQLite backup in a temporary directory.
"""

import argparse
import asyncio
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from brain import persona_loader
from nodes import echo, stories
from tools.check_echo import PAIRS
from utils import db, semantic_memory, logger


async def incident() -> bool:
    row = db.conn().execute("SELECT * FROM items WHERE id=20207").fetchone()
    if row is None or config.CHANNEL != "markets":
        raise RuntimeError("Treasury incident requires the markets database")
    incoming = dict(row)
    incoming["story_id"] = None
    at = datetime.fromisoformat(row["fetched_at"]).replace(tzinfo=timezone.utc)
    when = at.strftime("%Y-%m-%d %H:%M:%S")
    # Rewind this disposable snapshot: no later posts/threads are available to
    # retrieval, and a later summary cannot teach the model the eventual outcome.
    db.conn().execute("UPDATE posts SET status='draft' WHERE sent_at >= ?", (when,))
    db.conn().execute("UPDATE items SET story_id=NULL WHERE story_id IN (SELECT id FROM stories WHERE first_at >= ?)", (when,))
    db.conn().execute("DELETE FROM stories WHERE first_at >= ?", (when,))
    db.conn().execute("UPDATE items SET status='expired' WHERE fetched_at >= ?", (when,))
    for story in list(db.conn().execute("SELECT id FROM stories")):
        newest = db.conn().execute(
            "SELECT p.post_html,p.sent_at FROM posts p JOIN items i ON i.id=p.item_id "
            "WHERE i.story_id=? AND p.status='sent' ORDER BY p.sent_at DESC LIMIT 1", (story["id"],)
        ).fetchone()
        last = db.conn().execute("SELECT MAX(fetched_at) FROM items WHERE story_id=? AND fetched_at < ?",
                                 (story["id"], when)).fetchone()[0]
        if last:
            db.conn().execute("UPDATE stories SET last_item_at=? WHERE id=?", (last, story["id"]))
        if newest:
            db.conn().execute("UPDATE stories SET summary=?, last_post_at=? WHERE id=?",
                             (persona_loader.visible_text(newest["post_html"])[:300], newest["sent_at"], story["id"]))
    db.conn().commit()
    draft = "US 30-year Treasury yield rises to 5.656%"
    matches = await semantic_memory.published_matches(draft, now=at)
    print("Incident retrieval:", [(r["id"], round(r["score"], 3)) for r in matches], flush=True)
    repeat, why = await echo.repeats_something_published(draft, now=at)
    print("Treasury repeat:", "HOLD" if repeat else "SEND", why, flush=True)
    new_news_ok = True
    for text in ("US 30-year Treasury yield crosses 6% for the first time",
                 "US 30-year Treasury yield falls to 5.2%"):
        held, reason = await echo.repeats_something_published(text, now=at)
        print("Full-history new development:", "HOLD" if held else "SEND", text, reason, flush=True)
        new_news_ok = new_news_ok and not held
    candidates = await stories.placement_candidates(incoming, at)
    print("Story candidates:", [(s.id, s.status, s.name) for s in candidates], flush=True)
    chosen, reason, available = await stories.place(incoming, candidates, at)
    print("Placement:", chosen.id if chosen else None, reason, flush=True)
    gate_ok = False
    if chosen:
        chosen.absorb(incoming, at)
        gate = await stories.should_post(chosen, at)
        print("Story gate:", gate, flush=True)
        gate_ok = gate["verdict"] == "hold"
    return repeat and new_news_ok and any(r["id"] == 588 for r in matches) and available and chosen is not None and gate_ok


async def labelled() -> bool:
    wrong = 0
    cases = []
    for new_id, old_id, expected, note in PAIRS:
        pair = []
        for mid in (new_id, old_id):
            row = db.conn().execute("SELECT post_html FROM posts WHERE telegram_message_id=?", (mid,)).fetchone()
            if row is None:
                raise RuntimeError(f"missing labelled message {mid}")
            pair.append(persona_loader.visible_text(row[0]))
        cases.append((pair[0], pair[1], expected, note))
    cases.extend([
        ("US 30-year Treasury yield rises to 5.656%", "US 30-year yield reached 5.5185%, a 22-year high.", "hold", "incident: minor further climb"),
        ("US 30-year Treasury yield crosses 6% for the first time", "US 30-year yield reached 5.5185%, a 22-year high.", "send", "first whole-percent crossing"),
        ("US 30-year Treasury yield falls to 5.2%", "US 30-year yield rose to 5.5185%, a 22-year high.", "send", "direction reverses"),
        ("September CPI rises 0.3% month over month", "August CPI rose 0.3% month over month", "send", "new release period, same figure"),
    ])
    for new, old, expected, note in cases:
        answer = await echo._judge_history(new, "[previously published]\n"+old, persist=False)
        good = answer["verdict"] == expected
        wrong += not good
        print(f"{'PASS' if good else 'FAIL'} {answer['verdict']} (expected {expected}): {note} — {answer['reason']}", flush=True)
    print(f"Labelled cases: {len(cases)-wrong}/{len(cases)}", flush=True)
    return wrong == 0


async def roundup_incident() -> bool:
    from unittest.mock import patch
    row = db.conn().execute("SELECT post_html,sent_at FROM posts WHERE id=719").fetchone()
    if row is None or config.CHANNEL != "markets":
        raise RuntimeError("Roundup incident requires the markets database")
    at = datetime.fromisoformat(row["sent_at"]).replace(tzinfo=timezone.utc)
    text = persona_loader.visible_text(row["post_html"])
    matches = await semantic_memory.published_matches(text, now=at)
    print("Roundup retrieval:", len(matches), "posts; original coverage included:",
          {588, 707}.issubset({r["id"] for r in matches}), flush=True)
    good = {588, 707}.issubset({r["id"] for r in matches})
    orders = [("similarity", matches), ("reverse", list(reversed(matches))),
              ("date", sorted(matches, key=lambda r: r["sent_at"]))]
    for label, candidates in orders:
        with patch.object(semantic_memory, "published_matches", return_value=candidates):
            held, reason = await echo.repeats_something_published(text, now=at, persist=False)
        print("Roundup", label, "HOLD" if held else "SEND", reason, flush=True)
        good = good and held
    for proposed in (
        "US 30-year Treasury yield crosses 6% for the first time",
        "US 30-year Treasury yield falls to 5.2%",
        text + "\n\nThe Fed announced an emergency bond purchase program.",
    ):
        held, reason = await echo.repeats_something_published(proposed, now=at, persist=False)
        print("Roundup control", "HOLD" if held else "SEND", proposed, reason, flush=True)
        good = good and not held
    return good


async def run(args) -> bool:
    db.init_db()
    if args.backfill:
        count = await semantic_memory.backfill()
        print(f"{config.CHANNEL}: {count} published posts indexed; no messages sent", flush=True)
        return True
    okay = True
    if args.labelled:
        okay = await labelled()
    if args.incident:
        okay = await incident() and okay
    if args.roundup:
        okay = await roundup_incident() and okay
    return okay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--backfill", action="store_true")
    group.add_argument("--incident", action="store_true")
    group.add_argument("--labelled", action="store_true")
    group.add_argument("--roundup", action="store_true")
    parser.add_argument("--model", help="test a different reader-memory judge without changing settings")
    args = parser.parse_args()
    if args.model:
        config.ECHO_MODEL = args.model
    logger.setup(to_file=False)
    if args.backfill:
        okay = asyncio.run(run(args))
    else:
        with tempfile.TemporaryDirectory(prefix="reader-memory-") as directory:
            source = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
            target = Path(directory) / "rehearsal.db"
            destination = sqlite3.connect(target)
            source.backup(destination)
            destination.close()
            source.close()
            config.DB_PATH = target
            okay = asyncio.run(run(args))
            db.conn().close()
    sys.exit(0 if okay else 1)


if __name__ == "__main__":
    main()
