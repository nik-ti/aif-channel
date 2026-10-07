"""Fill the reader-memory cache: one embedding for every published post of the last
60 days, so the repeat check and story placement can compare against them.

Safe to run any time; it sends no messages and skips posts already cached.
Run: python3 tools/backfill_memory.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import db, logger, semantic_memory  # noqa: E402


async def main() -> None:
    db.init_db()
    count = await semantic_memory.backfill()
    print(f"{count} published posts indexed; no messages sent")


if __name__ == "__main__":
    logger.setup(to_file=False)
    asyncio.run(main())
