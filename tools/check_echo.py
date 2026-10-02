"""Test the exit check: does it hold repeats without killing real news?
Exit check fails open; model that cannot answer looks like one saying "send". Run --labelled before changing ECHO_MODEL.
Deepseek-v3.2 answered 7 of 8 pairs as prose not JSON, meaning the check was silent-broken.
Replay judges each post against only prior posts, showing what readers actually saw."""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from brain import persona_loader  # noqa: E402
from nodes import echo  # noqa: E402
from utils import embeddings, textclean  # noqa: E402

LINE = "─" * 74

# (newer message, older message, expected, what the pair tests). Hand-labelled
# 2026-09-29 from this channel's own posts. The first two are the repeat that
# prompted the check: the 30-year Treasury yield told twice in seven hours.
PAIRS = [
    (520, 518, "hold", "30y close 5.59% vs '30y highest since 2002', 7h apart"),
    (518, 501, "hold", "30y 'highest since 2002' vs 30y 5.5185%, 22-yr high"),
    (504, 479, "hold", "Apple $5 trillion, published twice"),
    (459, 446, "send", "House PASSES the bill vs House UNVEILS it"),
    (391, 369, "send", "ETF $120m OUTflows vs $643m INflows"),
    (328, 301, "send", "ETF $730m vs $101m inflows, different days"),
    (485, 484, "send", "10y passes 5% first time vs 30y at 5.367%"),
    (510, 488, "send", "Japan 2y above 1.9% vs Japan 10y at 3.055%"),
]


def _open() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _text(post_html: str) -> str:
    return persona_loader.visible_text(post_html).strip()


def _by_message(conn, mid: int) -> tuple[str, str]:
    row = conn.execute(
        "SELECT post_html, sent_at FROM posts "
        "WHERE telegram_message_id=? AND status IN ('sent', 'deleted')", (mid,)).fetchone()
    if row is None:
        raise SystemExit(f"message {mid} is not in this database")
    return _text(row["post_html"]), row["sent_at"]


async def labelled() -> bool:
    """The hand-labelled pairs. Returns True when all of them are right."""
    print(f"\nLABELLED PAIRS on {config.ECHO_MODEL}")
    print(LINE)
    conn = _open()
    broken = wrong = 0

    for new_id, old_id, expected, note in PAIRS:
        new_text, _ = _by_message(conn, new_id)
        old_text, old_when = _by_message(conn, old_id)
        verdict, reason = await echo._already_told(new_text, old_text, old_when)

        if verdict is None:
            broken += 1
            mark = "NO ANSWER — check fails open, so this reads as 'send'"
        elif verdict != expected:
            wrong += 1
            mark = f"WRONG, wanted {expected}"
        else:
            mark = "ok"
        print(f"  [{str(verdict):4}] {mark}")
        print(f"         {note}")
        print(f"         {reason[:110]}")

    print(LINE)
    print(f"   schema broken {broken}/{len(PAIRS)}, wrong {wrong}/{len(PAIRS)}")
    return broken == 0 and wrong == 0


async def replay(limit: int) -> None:
    """Every recent post, judged against what came before it."""
    print(f"\nREPLAY of the last {limit} posts on {config.ECHO_MODEL}")
    print(LINE)
    conn = _open()
    rows = conn.execute(
        "SELECT telegram_message_id AS mid, sent_at, post_html FROM posts "
        "WHERE status='sent' AND telegram_message_id IS NOT NULL "
        "ORDER BY sent_at DESC LIMIT ?", (limit,)).fetchall()

    posts = []
    for row in reversed(rows):
        text = _text(row["post_html"])
        if not text:
            continue
        vector = await embeddings.embed_one(textclean.for_embedding(text))
        if vector is None:
            print(f"   no embedding for message {row['mid']} — skipped")
            continue
        posts.append({"mid": row["mid"], "text": text, "vector": vector,
                      "when": datetime.fromisoformat(row["sent_at"])})
    print(f"   embedded {len(posts)} posts")

    window = timedelta(hours=config.ECHO_WINDOW_HOURS)
    held, sent, broken = [], [], 0

    for position, post in enumerate(posts):
        earlier = [p for p in posts[:position] if post["when"] - p["when"] <= window]
        if not earlier:
            continue
        closest = max(earlier, key=lambda p: embeddings.cosine(post["vector"], p["vector"]))
        score = embeddings.cosine(post["vector"], closest["vector"])
        if score < config.ECHO_SHORTLIST:
            continue

        verdict, reason = await echo._already_told(
            post["text"], closest["text"], closest["when"].isoformat(sep=" "))
        if verdict == "hold":
            held.append((post, closest, score, reason))
        elif verdict == "send":
            sent.append((post, closest, score, reason))
        else:
            broken += 1
            print(f"   NO ANSWER on message {post['mid']}: {reason}")

    print(f"   above the {config.ECHO_SHORTLIST} shortlist: "
          f"{len(held) + len(sent) + broken} pairs")
    print(f"   would hold {len(held)}, would send {len(sent)}, no answer {broken}")

    print(f"\nWOULD HOLD — read these: a hold on real news is the failure that matters")
    print(LINE)
    for post, closest, score, reason in held:
        print(f"  message {post['mid']} ({score:.3f}), because of {closest['mid']} "
              f"sent {closest['when']}")
        print(f"     already published: {closest['text'].splitlines()[0][:86]}")
        print(f"     would not go out:  {post['text'].splitlines()[0][:86]}")
        print(f"     {reason[:110]}\n")

    print(f"WOULD SEND")
    print(LINE)
    for post, closest, score, reason in sent:
        print(f"  message {post['mid']} ({score:.3f}) over {closest['mid']}: {reason[:96]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labelled", action="store_true",
                        help="only the hand-labelled pairs")
    parser.add_argument("--posts", type=int, default=60,
                        help="how many recent posts to replay (default 60)")
    parser.add_argument("--model", help="override ECHO_MODEL for this run")
    args = parser.parse_args()

    if args.model:
        config.ECHO_MODEL = args.model

    async def run() -> None:
        ok = await labelled()
        if not args.labelled:
            await replay(args.posts)
        if not ok:
            print("\n   The labelled set did not pass. Do not ship this model.")

    asyncio.run(run())


if __name__ == "__main__":
    main()
