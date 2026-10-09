# The story mechanism (Market One's, retired from AI Flow on 2026-10-09)

Market One followed running events — a war, a rate decision, an inflation print — as
**stories**: one thread per event, where every later post replied under the first one in
Telegram and only went out when the story had actually moved. It worked well there. AI Flow
inherited it, but AI news is mostly one-off launches: in its last three days on AI Flow it
made no threads, and mostly re-filed repeats the duplicate check had already caught. AI Flow
switched it off (`config.STORIES = False`) and now limits posts per company instead.

## How it worked
1. **Dedup files instead of deleting.** When the dedup judge ruled "same event" on two items
   written differently, the newer item was attached to the older one's story as `held`, so
   its extra facts could reach the story's next post.
2. **Story organizer** (`stories.place`) — a model chose which open story an item joins, or
   opened a new one. It saw every open story, plus related closed ones from reader memory.
3. **Gatekeeper** (`stories.should_post`) — a model asked "has this story moved since its
   last post?": post, hold the item as fuel, or "not this story" (re-file it on its own).
4. **Writing from the whole story** — `stories.as_source` folded the story's waiting items
   into one source, and `brief_for_writer` told the writer what the reader was already told.
5. **Threads** — every later post replied to the story's first message.
6. **Coverage in code** (`coverage.py`) — after a post, an item counted as covered only if
   the post repeated a detail that only that item supplied. No model decides this.
7. **Roundups** — a story holding `STORY_DIGEST_ITEMS` items for `STORY_DIGEST_MINUTES` was
   asked once more whether they add up to something new; past `STORY_DIGEST_MAX_QUIET_HOURS`
   it was over.

## What is here
| File | What it is |
|---|---|
| `stories.py` | placement, the gate, naming, folding, the writer brief, hydration from the DB |
| `coverage.py` | which waiting items a story post really covered |
| `stations_story_nodes.py` | the story-aware dedup station and the two story stations, as they were in `pipeline/stations.py` |
| `replay_stories.py` | backtest: replays history through placement and the gate |
| `dashboard_api_stories.py`, `StoriesView.tsx` | the dashboard's Stories endpoint and tab |

The design and the case that shaped it: `docs/spec-story-continuity-2026-10-05.md`.
The database helpers (`create_story`, `attach_item_to_story`, `record_story_post`,
`stories_due_for_roundup`...) are still in `utils/db.py`, and the `stories` table is still
in the database with its history.

## Bringing it back
- **While the code is still in the repo (until about 2026-10-16):** set `STORIES = True` in
  `config.py` and restart. The graph wires the story stations back in place of the company
  limit, and the publish loop runs the roundups again. Put the Stories tab back from the
  two dashboard files here.
- **After the code is removed:** the whole working version is in git tag
  `market-one-final` (commit 6183763) — `git checkout market-one-final -- nodes/stories.py
  nodes/coverage.py`, and copy the stations from `stations_story_nodes.py` back into
  `pipeline/stations.py` and their edges into `pipeline/graph.py` (see the graph in
  `../../RESTORE.md`). The story settings are in that tag's `config.py` under `# STORIES`.
