"""Check the labeler on real items with hand-checked labels (tests/fixtures/label_cases.json).
Calls the real model, records nothing. Run it before changing the labeler's prompt or model.

    python3 tools/check_labels.py [--model provider/model] [--prompt other_labeler.md]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

config.DB_PATH = Path(tempfile.mkdtemp()) / "check.db"     # a failure count must not reach the live DB

from nodes import labeler  # noqa: E402
from utils import db  # noqa: E402

CASES = ROOT / "tests" / "fixtures" / "label_cases.json"


class Row(dict):
    def keys(self):  # the labeler reads rows the way sqlite3.Row offers them
        return super().keys()


async def main() -> int:
    db.init_db()
    cases = json.loads(Path(CASES).read_text())
    gate = asyncio.Semaphore(3)        # more in flight hit OpenRouter's budget guard (HTTP 402)

    async def one(case):
        async with gate:
            return case, await labeler.execute(Row(case))

    results = await asyncio.gather(*(one(c) for c in cases))
    kinds = companies = 0
    for case, got in results:
        kind_ok, company_ok = got["kind"] == case["kind"], got["company"] == case["company"]
        kinds += kind_ok
        companies += company_ok
        if not (kind_ok and company_ok):
            print(f"#{case['id']} {case['title'][:70]}\n"
                  f"    expected {case['kind']}/{case['company']}, got {got['kind']}/{got['company']}"
                  f" — {got['reason'][:150]}")
    n = len(results)
    print(f"\nKind right {kinds}/{n}, company right {companies}/{n}  ({config.LABELER_MODEL})")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", help="try another model")
    parser.add_argument("--prompt", help="try another prompt file in prompts/")
    parser.add_argument("--cases", help="another cases file of the same shape")
    args = parser.parse_args()
    if args.cases:
        CASES = Path(args.cases)
    if args.model:
        config.LABELER_MODEL = args.model
    if args.prompt:
        labeler.PROMPT = (config.PROMPTS / args.prompt).read_text()
    sys.exit(asyncio.run(main()))
