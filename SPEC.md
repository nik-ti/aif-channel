# Market One sorter rubric and model upgrade

## What we're improving
On 2026-10-06 Market One posted "Flames and smoke seen at Venezuela's Cardon
refinery" and "Unverified reports of fire over Saudi Arabia's largest oil field".
The sorter scored both 4 on "could disrupt supply". Nothing had stopped, and the
Saudi claim came from Iranian state media. Over the past month the same mistake
let through five more sightings and war-side claims. The rubric had grown to
2,952 words of patches, each added after one bad post, and the model followed it
loosely. nikita asked for a simpler rubric, not another rule. The previous spec
is preserved in docs/spec-story-continuity-2026-10-05.md.

## Contract
GOAL: one short rubric built around nikita's own test, "which major asset's
price will this move?". Its decisions must match his post/skip labels better
than the old rubric on the same past items, and it must hold back rumours,
sightings and small assets. Then pick the sorter and writer models on measured
schema compliance, agreement, accuracy and cost.

CONSTRAINTS:
- Market One only. AI Flow keeps its own rubric and its current models until
  it is measured separately.
- No change to the schema, the `none` → 3 cap, or anything after the writer.
- Cost stays in the same range: a few dollars a month for these two stations.
- Replays never write to the live database and never post.

FORMAT:
- `channels/markets/rubric.md`: an explicit major-asset list, then four tests
  for a 4: real, new, striking, now. Short worked examples, taken from items
  nikita labelled.
- Models live in the channel profile (`SORTER_MODEL`, `WRITER_MODEL`); config.py
  reads them through `getattr(_profile, …)`, and `.env` still wins.
- The markets sorter is told today's date (`SORTER_SHOWS_DATE`).
- `writer.figures_lost_by_cut`: the one-line-source cut never deletes a
  figure that came from the source.

FAILURE (any of these = not done):
1. The new rubric agrees with nikita's labels less often than the old one, or
   posts many fewer of the striking market facts he wants (records, big moves).
2. A sighting, a rumour or a war-side damage claim scores 4 without a confirmed
   supply effect.
3. A chosen model returns the wrong JSON shape on more than 1% of calls, or is
   served by providers that ignore the schema.
4. The writer's posts are approved by the live editor less often than the old
   writer's, or they contain more figures that are not in the source.
5. AI Flow's models or rubric change as a side effect.

## Built on top of
- OpenRouter model catalogue and endpoints:
  https://openrouter.ai/api/v1/models, /models/<id>/endpoints (providers per model)
- Usage accounting in responses (`usage: {include: true}`) for the real cost of each call.
- The live editor as a judge, after checking it on planted Tesla errors: it
  rejected all four kinds of error 3/3 and approved both correct versions 3/3.
- nikita's labels: artifact https://claude.ai/artifact/QFE7gctnRjtZu2fntSUknV
  (41 post/skip answers + 8 he named in chat).

## Gotchas we're handling
- The project's model helper retries, and falls back when a format breaks.
  That hides schema failures, so the model test used a raw call with no
  safety nets.
- Over-tightening: a first "has it happened?" draft cut posts from 104 to 55 of
  400 items, and nikita disagreed with it more. He wants striking market facts,
  not only hard state changes.
- Over-loosening: a "striking" draft posted 165 of 400, letting in leader
  remarks, market odds and ETF-flow streaks. Fixed with "words are not
  actions" and a background list.
- Thinking budgets: gemini-3.8-flash ran out of room on 9 of 250 sorter calls
  and 24 of 40 writer calls. It is not a drop-in model.
- Concurrency against a small balance: OpenRouter refuses in-flight requests
  that together could exceed the remaining credit (HTTP 402). Run tests at
  three requests at a time and stop at the first 402.
- Examples inside the rubric are also test items, so agreement on those items
  is flattering. Compare models with each other, not against a perfect score.

## Build sequence
1. Label past items (artifact), and replay old and new rubrics on 400 items.
2. Iterate the rubric until it agrees with nikita more and lets fewer rumours through.
3. Fix the date blind spot and the one-line cut that dropped estimates.
4. Raw-call model test: 7 sorter candidates × 250 calls, 6 writers × 40 posts.
5. Move models into the profile, show them per channel on the dashboard, restart.

## How to run and test
- Existing tests: `CHANNEL=markets /usr/bin/python3 tests/test_markets_unchanged.py`
  (the sorter-prompt hash was updated for the new rubric),
  `CHANNEL=ai_news /usr/bin/python3 tests/test_ai_channel.py`, `tests/test_macro.py`,
  `tests/test_media.py`, `tests/test_reader_memory.py`.
- Models in effect: `CHANNEL=markets /usr/bin/python3 -c "import config; print(config.SORTER_MODEL, config.WRITER_MODEL)"`.
- Live schema health: `counters` rows `schema_ok:<model>` / `schema_bad:<model>`.

## Status
_Updated: 2026-10-06_
- Rubric live at 21:47 UTC. On 400 past items it posts 119 (old 104), agrees
  with nikita on 40/49 (old 37/49), and holds every sighting and war-side claim
  in the set.
- Models live at 22:37 UTC. Sorter `google/gemini-3.5-flash-lite`: 100%
  schema, 43/49, 1 of 14 traps through (old model 5), ~$3/month. Writer
  `openai/gpt-6-luna`: 31/40 editor-approved (deepseek-v3.2 24/40), 1 invented
  figure (old 2), ~$0.0003 a post.
- Not adopted: claude-sonnet-5.5 (same agreement at 10× the price),
  gemini-3.8-flash (thinking budget), claude-haiku-4.5 (5 invented figures),
  deepseek-v4.x (29 providers, schema roulette).
- Open: the editor rejects many drafts on nitpicks ("market" vs "markets").
  AI Flow has not been measured on the new models yet.
