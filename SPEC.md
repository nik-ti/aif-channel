# Labels, company limits and a daily digest instead of stories

## What we're improving
Stories (one running thread per event) were built for Market One's wars and rate decisions.
On AI Flow they made no threads in three days and mostly re-filed what the duplicate check had
already caught, while getting it wrong both ways (held GPT-6.1 Sol Ultrafast, lumped two Managed
Agents launches together). The sorter also had one catch-all kind, "launch", for 23 of 29 posts.
nikita decided (2026-10-09): label every item with a kind and a company from fixed lists, retire
stories, widen the duplicate check to 7 days, and cap each company at 2 posts a day with the
rest going into one evening digest. Earlier specs are in docs/.

## Contract
GOAL:
- Every item that passes dedup gets a kind and a company from fixed lists, shown on the dashboard.
- A roundup ("DAILY AI BRIEF") is dropped and never posted.
- No story is placed, gated or threaded; a same-event repeat within 7 days is dropped.
- A company's 3rd+ post of the day (UTC) waits; at DIGEST_HOUR_UTC its waiting items go out as
  one bullet post (or a normal post if only one waits). A 5/5 item always posts.
- The dashboard has no Stories tab and shows kinds, companies, waiting items and the new graph;
  its guide and the README describe the new flow.

CONSTRAINTS:
- Labeler uses a cheap model (gemini-3.5-flash-lite), its own prompt in prompts/labeler.md.
- The dedup judge's prompt is not edited (tuned on hand-labelled pairs).
- Story code stays in the repo, switched off by config.STORIES, for a week; a copy goes to
  archive/market-one/ with notes. Same DB, new columns added by the existing migration list.

FORMAT: nodes/labeler.py, nodes/company_digest.py, prompts/labeler.md; stations and graph
wired by config; dashboard backend + frontend updated; README, SPEC, archive notes.

FAILURE (any of these = not done):
1. A label outside the fixed lists is stored (typo, new spelling, empty).
2. A roundup reaches the writer.
3. Any story station runs, or a post goes out as a reply, while STORIES is off.
4. A company gets a 3rd separate post in a UTC day from items scored below 5.
5. Waiting items are never posted or never expire (left waiting forever), or a digest posts twice in a day.
6. A same-event repeat 2-7 days after a published post is posted again.
7. The dashboard still shows a Stories tab / story stations, fails to build, or its guide describes stories.
8. Existing tests fail.

## Built on top of
- Existing machinery reused: sorter-style strict JSON schema (utils/openrouter.chat_json),
  the reserve's "waiting status" pattern, stories.as_source's folding + media.merge for the
  digest source, the writer's brief slot, the meta table for "digest done today".

## Gotchas we're handling
- A model can return a value off the list despite the schema: code maps it to "other".
- "other" kind no longer means irrelevant; relevance is the sorter's own yes/no.
- Old items keep their old kinds (launch/resource); reserve items labelled "resource" become "guide".
- Waiting items must not be swept by the 90-minute queue expiry (different status), and must
  expire after DIGEST_MAX_WAIT_HOURS so nothing waits forever.
- A digest is marked done before it runs, so a crash cannot send it twice.
- The writer's "roundup: pick one item" rule must not fire on our own digest: the brief overrides it.

## Build sequence
1. Spec + failing tests. 2. Labeler + sorter change. 3. Stories off + 7-day dedup.
4. Company limit + digest. 5. Dashboard. 6. Archive, README, guide. 7. Verify live.

## How to run and test
- `/usr/bin/python3 tests/test_ai_channel.py`, `/usr/bin/python3 tests/test_media.py`,
  `/usr/bin/python3 -m unittest tests/test_reader_memory.py`, `/usr/bin/python3 tests/test_labels_and_digest.py`
- `/usr/bin/python3 tools/check_labels.py` — the labeler against hand-checked labels
- `cd dashboard/frontend && npx tsc --noEmit && npm run build`

## Status
_Updated: 2026-10-09_
- All 7 steps done and live (aif-channel restarted 17:34 UTC; first items labelled correctly).
- Labeler (gemini-3.5-flash-lite): 60-61/61 on the tuned cases, 13/15 kinds and 15/15
  companies on 15 unseen ones. skills.sh items are forced to "skill" in code. Prompt fixes
  from the first run: hardware is always "other"; new_product only for listed companies,
  the same from anyone else is "tool"; a new thing inside any product is "feature".
- Stories are off by config.STORIES; their code stays until ~2026-10-16, then delete
  nodes/stories.py, nodes/coverage.py, the story stations/routes and STORY_* settings
  (copy and restore notes: archive/market-one/code/stories/).
- Route words in pipeline/stations.py are the graph's arrow labels; the channel saves
  LangGraph's diagram to meta.graph_mermaid at every start, and the dashboard draws it.
- With stories off the "place only" rounds are gone: a non-forced item that may not be
  sent this round is left queued (publish_loop), since nothing would stop it otherwise.
- Today's per-company counts start from the restart: items before it have no company.
- Pending (nikita asked to be reminded): tie the "try it" link search to the kind.
