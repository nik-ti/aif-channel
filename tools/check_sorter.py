"""Replay labelled sources against the real sorter without writing to the channel DB.

Run python3 tools/check_sorter.py --runs 2. Model calls cost money; no posts are sent.
"""

import argparse
import asyncio
import importlib.util
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config
from nodes import sorter
from utils import openrouter


async def run(args):
    judge = sorter
    if args.sorter_file:
        spec = importlib.util.spec_from_file_location("sorter_baseline", args.sorter_file)
        judge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(judge)
    if args.prompt:
        judge.PROMPT = args.prompt.read_text()
    cases = json.loads(args.cases.read_text())
    if args.only:
        cases = [case for case in cases if case["name"] in args.only.split(",")]
        if not cases:
            raise ValueError("No cases matched --only")
    results = []
    semaphore = asyncio.Semaphore(3)

    async def check(case, repetition):
        async with semaphore:
            started = time.monotonic()
            verdict = await judge.execute(case["item"])
            publishes = verdict["relevant"] and verdict["importance"] >= config.MIN_IMPORTANCE
            passed = not verdict["fallback"] and publishes == case["publish"]
            for key in ("basis", "relevant"):
                if key in case and key in judge.SCHEMA["properties"]:
                    passed = passed and verdict.get(key) == case[key]
            result = {"name": case["name"], "run": repetition, "passed": passed,
                      "seconds": round(time.monotonic() - started, 2), "verdict": verdict}
            results.append(result)
            print(f"{'PASS' if passed else 'FAIL'} {case['name']} run {repetition}: "
                  f"{verdict.get('basis', '-')} / {verdict['importance']} / {verdict['reason']}", flush=True)

    async def without_telemetry(**kwargs):
        kwargs["user"] = openrouter.with_now(kwargs["user"])
        return await openrouter._chat_json_once(**kwargs)

    with tempfile.TemporaryDirectory() as folder, \
            patch.object(config, "DB_PATH", Path(folder) / "eval.db"), \
            patch.object(openrouter, "chat_json", side_effect=without_telemetry):
        await asyncio.gather(*(check(case, repetition) for repetition in range(1, args.runs + 1)
                               for case in cases))
    passed = sum(r["passed"] for r in results)
    errors = sum(r["verdict"]["fallback"] for r in results)
    print(f"{passed}/{len(results)} matched; {errors} model/answer failures")
    if args.output:
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--cases", type=Path, default=ROOT / "tests/fixtures/sorter_cases.json")
    parser.add_argument("--only", help="Comma-separated case names")
    parser.add_argument("--prompt", type=Path)
    parser.add_argument("--sorter-file", type=Path, help="Compare a saved sorter implementation")
    parser.add_argument("--output", type=Path)
    sys.exit(asyncio.run(run(parser.parse_args())))
