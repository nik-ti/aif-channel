"""Check the editor on known cases: faithful rewrites it must approve and posts with one
planted falsehood it must reject (tests/fixtures/editor_cases.json). Calls the real model,
records nothing. Run it before changing the editor's prompt or model.

    python3 tools/check_editor.py [--runs 3] [--prompt other_editor.md] [--model provider/model]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nodes import editor  # noqa: E402
from utils import logger  # noqa: E402

CASES = ROOT / "tests" / "fixtures" / "editor_cases.json"


async def judge(case: dict, source: dict) -> tuple[bool, str]:
    item = {"id": 0, "topic_hint": "", **source}
    verdict = await editor.execute(item, case["post"], 0, record=False)
    return verdict["approved"], f"{verdict.get('rules_broken')} {verdict.get('reason', '')[:160]}"


async def main(runs: int) -> int:
    data = json.loads(CASES.read_text())
    right = total = 0
    for case in data["cases"]:
        source = data["sources"][case["source"]]
        results = await asyncio.gather(*(judge(case, source) for _ in range(runs)))
        ok = [(approved == (case["expect"] == "approve")) for approved, _ in results]
        right += sum(ok)
        total += len(ok)
        mark = "✅" if all(ok) else ("⚠️ " if any(ok) else "❌")
        print(f"{mark} {case['id']:<32} expect {case['expect']:<8} {sum(ok)}/{runs} right")
        for (approved, why), good in zip(results, ok):
            if not good:
                print(f"      wrongly {'approved' if approved else 'rejected'}: {why}")
    print(f"\n{right}/{total} judgements right")
    return 0 if right == total else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--prompt", help="try another editor prompt file instead of prompts/editor.md")
    parser.add_argument("--model", help="try another model (no fallback) instead of config.EDITOR_MODEL")
    args = parser.parse_args()
    if args.model:
        editor.MODEL, editor.FALLBACKS = args.model, []
    if args.prompt:
        editor.PROMPT = Path(args.prompt).read_text()
    logger.setup(level="WARNING", to_file=False)
    sys.exit(asyncio.run(main(args.runs)))
